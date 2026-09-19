"""Chat engine over Azure OpenAI with a tool-calling loop.

Authentication is Entra-only via DefaultAzureCredential; no keys are read anywhere.
"""

from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from typing import Any, Awaitable, Callable

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

from .config import get_settings
from .contracts import ToolCall

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[Any]]

# Bound fan-out so the configured deployment is not overwhelmed by a workflow burst.
MODEL_REQUEST_GATE = asyncio.Semaphore(get_settings().model_max_concurrency)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Models frequently wrap JSON in Markdown fences or add prose. Recover regardless."""
    if not text:
        return {}
    candidates: list[str] = []
    fenced = _JSON_FENCE.findall(text)
    candidates.extend(fenced)
    candidates.append(text)
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return {}


class ChatEngine:
    """Thin wrapper around the Azure OpenAI chat completions API with tool support."""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._client: AsyncAzureOpenAI | None = None
        if settings.has_openai:
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                "https://cognitiveservices.azure.com/.default",
            )
            self._client = AsyncAzureOpenAI(
                azure_endpoint=settings.openai_endpoint,
                azure_ad_token_provider=token_provider,
                api_version=settings.api_version,
                timeout=settings.request_timeout,
                max_retries=3,
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    async def complete(
        self,
        instructions: str,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        handlers: dict[str, ToolHandler] | None = None,
        force_json: bool = True,
        max_tool_rounds: int = 4,
    ) -> tuple[str, list[ToolCall], dict[str, int]]:
        if self._client is None:
            raise RuntimeError("Azure OpenAI is not configured (AZURE_OPENAI_ENDPOINT missing).")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ]
        collected: list[ToolCall] = []
        usage = {"prompt": 0, "completion": 0}
        handlers = handlers or {}

        for _ in range(max_tool_rounds + 1):
            kwargs: dict[str, Any] = {
                "model": self._settings.model_deployment,
                "messages": messages,
            }
            if self._settings.supports_temperature:
                kwargs["temperature"] = 0.2
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if force_json and not tools:
                kwargs["response_format"] = {"type": "json_object"}

            async with MODEL_REQUEST_GATE:
                response = await self._client.chat.completions.create(**kwargs)

            if response.usage:
                usage["prompt"] += response.usage.prompt_tokens or 0
                usage["completion"] += response.usage.completion_tokens or 0

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                return (message.content or "", collected, usage)

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                name = tool_call.function.name
                raw_args = tool_call.function.arguments or "{}"
                started = time.perf_counter()
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}

                handler = handlers.get(name)
                if handler is None:
                    result_text = json.dumps({"error": f"unknown tool '{name}'"})
                else:
                    try:
                        result = await handler(**args)
                        result_text = json.dumps(result, default=str)
                    except Exception as exc:
                        logger.warning("Tool %s failed: %s", name, exc)
                        result_text = json.dumps({"error": str(exc)})

                duration_ms = int((time.perf_counter() - started) * 1000)
                collected.append(
                    ToolCall(
                        tool_name=name,
                        arguments=raw_args[:2000],
                        result=result_text[:2000],
                        duration_ms=duration_ms,
                    )
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result_text[:12000]}
                )

        # Tool budget exhausted: ask once more for a final answer without tools.
        final_kwargs: dict[str, Any] = {
            "model": self._settings.model_deployment,
            "messages": messages + [{"role": "user", "content": "Provide your final JSON answer now."}],
        }
        if self._settings.supports_temperature:
            final_kwargs["temperature"] = 0.2
        async with MODEL_REQUEST_GATE:
            final = await self._client.chat.completions.create(**final_kwargs)
        if final.usage:
            usage["prompt"] += final.usage.prompt_tokens or 0
            usage["completion"] += final.usage.completion_tokens or 0
        return (final.choices[0].message.content or "", collected, usage)


_engine: ChatEngine | None = None


def get_engine() -> ChatEngine:
    global _engine
    if _engine is None:
        _engine = ChatEngine()
    return _engine
