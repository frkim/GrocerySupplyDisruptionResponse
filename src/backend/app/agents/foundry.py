"""Stores the FOUNDRY-mode agents in a Microsoft Foundry project and executes them there.

Targets the current Foundry agent model (azure-ai-projects 2.x): each agent is persisted as a
versioned ``PromptAgentDefinition`` through ``agents.create_version``, so it is listed in the
Foundry portal, and is invoked through the Responses API with an ``agent_reference`` so runs,
tool calls and token usage are attributed to that agent rather than to a bare model call.

The previous Assistants-style API (``create_agent`` / threads / runs) does not exist on this
SDK, which is why nothing was ever persisted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any

from ..config import get_settings
from ..contracts import HostingMode, ToolCall
from ..llm import MODEL_REQUEST_GATE
from .definitions import AGENTS, AgentSpec
from .tools import handlers_for, schemas_for

logger = logging.getLogger(__name__)

APP_TAG = "grocery-supply-disruption-response"
_FINGERPRINT_KEY = "definitionHash"
_NAME_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")

# Agents that retrieve from the corpus get native Foundry grounding as well.
KNOWLEDGE_TOOL = "search_knowledge"

_state: dict[str, Any] = {
    "checked": False,
    "client": None,
    "credential": None,
    "openai": None,
    "agents": {},
    "errors": {},
    "provisioned": False,
    "knowledgeConnection": None,
}
_provision_lock = asyncio.Lock()


def _kebab(value: str) -> str:
    """CamelCase agent names become portal-friendly hyphenated names."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", value)
    return _NAME_SEPARATORS.sub("-", spaced).strip("-").lower()


def agent_name_for(spec: AgentSpec) -> str:
    """Foundry names must be alphanumeric with inner hyphens and at most 63 characters."""
    prefix = get_settings().foundry_agent_prefix.strip()
    raw = f"{prefix}-{spec.name}" if prefix else spec.name
    return _kebab(raw)[:63].strip("-")


def _fingerprint(spec: AgentSpec, knowledge_connection: str | None) -> str:
    settings = get_settings()
    payload = json.dumps(
        {
            "model": settings.model_deployment,
            "generationParameters": "default" if not settings.supports_temperature else "temperature-0.2",
            "instructions": spec.instructions,
            "tools": sorted(spec.tools),
            "mcp": settings.mcp_server_url,
            "knowledge": {
                "connection": knowledge_connection or "",
                "index": settings.search_index,
                "queryType": settings.knowledge_query_type,
                "topK": settings.knowledge_top_k,
            },
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def uses_knowledge(spec: AgentSpec) -> bool:
    return KNOWLEDGE_TOOL in spec.tools


async def _knowledge_connection(client) -> str | None:
    """Resolve the project connection that fronts the knowledge index, once."""
    cached = _state["knowledgeConnection"]
    if cached is not None:
        return cached or None

    settings = get_settings()
    if not settings.enable_foundry_knowledge:
        _state["knowledgeConnection"] = ""
        return None

    wanted = settings.knowledge_connection_name.strip().lower()
    try:
        async for connection in client.connections.list():
            if "search" not in str(getattr(connection, "type", "")).lower():
                continue
            if wanted and connection.name.lower() != wanted:
                continue
            resolved = getattr(connection, "id", None) or connection.name
            _state["knowledgeConnection"] = resolved
            logger.info("Knowledge connection resolved: %s", connection.name)
            return resolved
        logger.warning("No Azure AI Search connection named %r in the project.", wanted)
    except Exception as exc:
        logger.warning("Could not resolve the knowledge connection: %s", exc)

    _state["knowledgeConnection"] = ""
    return None


def _tool_definitions(spec: AgentSpec, knowledge_connection: str | None) -> list[Any]:
    """Publish each Python function tool as a Foundry function tool, plus knowledge and MCP."""
    from azure.ai.projects.models import FunctionTool

    tools: list[Any] = []
    for schema in schemas_for(spec.tools):
        function = schema["function"]
        tools.append(
            FunctionTool(
                name=function["name"],
                description=function.get("description"),
                parameters=function["parameters"],
                strict=False,
            )
        )

    settings = get_settings()
    if knowledge_connection and uses_knowledge(spec):
        from azure.ai.projects.models import (
            AISearchIndexResource,
            AzureAISearchTool,
            AzureAISearchToolResource,
        )

        tools.append(
            AzureAISearchTool(
                azure_ai_search=AzureAISearchToolResource(
                    indexes=[
                        AISearchIndexResource(
                            project_connection_id=knowledge_connection,
                            index_name=settings.search_index,
                            query_type=settings.knowledge_query_type,
                            top_k=settings.knowledge_top_k,
                        )
                    ]
                )
            )
        )

    if settings.mcp_server_url:
        try:
            from azure.ai.projects.models import MCPTool

            tools.append(
                MCPTool(
                    server_label=settings.mcp_server_label or "external-mcp",
                    server_url=settings.mcp_server_url,
                    require_approval="never",
                )
            )
        except Exception as exc:
            logger.warning("Could not attach MCP tool to %s: %s", spec.name, exc)
    return tools


async def _ensure_client():
    """Resolve the project client once; None means Foundry hosting is unavailable."""
    if _state["checked"]:
        return _state["client"]

    _state["checked"] = True
    settings = get_settings()
    if not (settings.enable_foundry_hosted and settings.ai_project_endpoint):
        logger.info("Foundry hosting disabled or no project endpoint configured.")
        return None

    try:
        from azure.ai.projects.aio import AIProjectClient
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential()
        client = AIProjectClient(
            endpoint=settings.ai_project_endpoint,
            credential=credential,
        )
        _state["credential"] = credential
        _state["client"] = client
        _state["openai"] = client.get_openai_client()
        logger.info("Foundry project client ready for %s", settings.ai_project_endpoint)
        return client
    except Exception as exc:
        logger.warning("Foundry project client unavailable (%s).", exc)
        _state["client"] = None
        return None


async def _latest_version(client, agent_name: str):
    try:
        async for version in client.agents.list_versions(agent_name, limit=1, order="desc"):
            return version
    except Exception:
        return None
    return None


async def ensure_agent(spec: AgentSpec) -> dict[str, Any] | None:
    """Create or reuse the stored Foundry agent version for one spec."""
    cached = _state["agents"].get(spec.name)
    if cached is not None:
        return cached

    client = await _ensure_client()
    if client is None:
        return None

    from azure.ai.projects.models import PromptAgentDefinition

    settings = get_settings()
    name = agent_name_for(spec)
    knowledge_connection = await _knowledge_connection(client)
    grounded = bool(knowledge_connection and uses_knowledge(spec))
    fingerprint = _fingerprint(spec, knowledge_connection)

    existing = await _latest_version(client, name)
    if existing is not None and (existing.metadata or {}).get(_FINGERPRINT_KEY) == fingerprint:
        record = {
            "specName": spec.name,
            "agentName": name,
            "version": existing.version,
            "id": existing.id,
            "toolCount": len(spec.tools),
            "knowledge": grounded,
            "created": False,
        }
    else:
        definition_kwargs = {
            "model": settings.model_deployment,
            "instructions": spec.instructions,
            "tools": _tool_definitions(spec, knowledge_connection),
        }
        if settings.supports_temperature:
            definition_kwargs["temperature"] = 0.2
        created = await client.agents.create_version(
            agent_name=name,
            definition=PromptAgentDefinition(**definition_kwargs),
            description=spec.description[:512],
            metadata={
                _FINGERPRINT_KEY: fingerprint,
                "app": APP_TAG,
                "nodeId": spec.node_id.value,
                "label": spec.label[:512],
                "knowledge": "azure-ai-search" if grounded else "none",
            },
        )
        record = {
            "specName": spec.name,
            "agentName": name,
            "version": created.version,
            "id": created.id,
            "toolCount": len(spec.tools),
            "knowledge": grounded,
            "created": True,
        }
        logger.info(
            "Stored Foundry agent %s version %s (knowledge=%s)", name, created.version, grounded
        )

    _state["agents"][spec.name] = record
    _state["errors"].pop(spec.name, None)
    return record


async def provision_all() -> dict[str, Any]:
    """Publish every FOUNDRY-mode agent so the project lists them without waiting for a run."""
    async with _provision_lock:
        client = await _ensure_client()
        if client is None:
            return {"enabled": False, "agents": [], "errors": {}}

        for spec in AGENTS:
            if spec.hosting_mode is not HostingMode.FOUNDRY:
                continue
            try:
                await ensure_agent(spec)
            except Exception as exc:
                logger.warning("Could not store Foundry agent %s: %s", spec.name, exc)
                _state["errors"][spec.name] = str(exc)

        _state["provisioned"] = True
        return provisioning_status()


def provisioning_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": bool(settings.enable_foundry_hosted and settings.ai_project_endpoint),
        "projectEndpoint": settings.ai_project_endpoint,
        "provisioned": _state["provisioned"],
        "knowledgeConnection": _state["knowledgeConnection"] or None,
        "knowledgeIndex": settings.search_index if _state["knowledgeConnection"] else None,
        "agents": list(_state["agents"].values()),
        "errors": dict(_state["errors"]),
    }


async def _execute_tool(name: str, raw_args: str, handlers: dict[str, Any]) -> tuple[str, int]:
    started = time.perf_counter()
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        args = {}

    handler = handlers.get(name)
    if handler is None:
        result_text = json.dumps({"error": f"unknown tool '{name}'"})
    else:
        try:
            result_text = json.dumps(await handler(**args), default=str)
        except Exception as exc:
            logger.warning("Foundry tool %s failed: %s", name, exc)
            result_text = json.dumps({"error": str(exc)})
    return result_text, int((time.perf_counter() - started) * 1000)


async def run_prompt_agent(
    spec: AgentSpec, prompt: str
) -> tuple[str, list[ToolCall], dict[str, int]] | None:
    """Run the stored agent through the Responses API. None means Foundry could not serve it."""
    record = await ensure_agent(spec)
    if record is None:
        return None

    client = _state["openai"]
    if client is None:
        return None

    settings = get_settings()
    handlers = handlers_for(spec.tools)
    reference = {
        "agent_reference": {
            "type": "agent_reference",
            "name": record["agentName"],
            "version": record["version"],
        }
    }
    collected: list[ToolCall] = []
    usage = {"prompt": 0, "completion": 0}
    payload: Any = prompt
    previous_id: str | None = None

    for _ in range(settings.foundry_max_tool_rounds + 1):
        kwargs: dict[str, Any] = {"input": payload, "extra_body": reference}
        if previous_id:
            kwargs["previous_response_id"] = previous_id

        async with MODEL_REQUEST_GATE:
            response = await client.responses.create(**kwargs)

        if getattr(response, "usage", None):
            usage["prompt"] += getattr(response.usage, "input_tokens", 0) or 0
            usage["completion"] += getattr(response.usage, "output_tokens", 0) or 0

        previous_id = response.id
        calls = [item for item in (response.output or []) if getattr(item, "type", "") == "function_call"]
        if not calls:
            return (response.output_text or "", collected, usage)

        outputs: list[dict[str, Any]] = []
        for call in calls:
            result_text, duration_ms = await _execute_tool(call.name, call.arguments, handlers)
            collected.append(
                ToolCall(
                    tool_name=call.name,
                    arguments=(call.arguments or "")[:2000],
                    result=result_text[:2000],
                    duration_ms=duration_ms,
                )
            )
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": result_text[:12000],
                }
            )
        payload = outputs

    async with MODEL_REQUEST_GATE:
        final = await client.responses.create(
            input="Provide your final JSON answer now.",
            extra_body=reference,
            previous_response_id=previous_id,
        )
    if getattr(final, "usage", None):
        usage["prompt"] += getattr(final.usage, "input_tokens", 0) or 0
        usage["completion"] += getattr(final.usage, "output_tokens", 0) or 0
    return (final.output_text or "", collected, usage)


async def close() -> None:
    for key in ("openai", "client", "credential"):
        resource = _state.get(key)
        if resource is None:
            continue
        try:
            await resource.close()
        except Exception:
            logger.debug("Closing Foundry %s failed", key, exc_info=True)
    _state.update(
        {
            "checked": False,
            "client": None,
            "credential": None,
            "openai": None,
            "knowledgeConnection": None,
        }
    )

