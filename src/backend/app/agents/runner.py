"""Executes an agent in whichever hosting mode it declares.

Three genuinely different execution paths are demonstrated:

* FOUNDRY - invoked through a Microsoft Foundry hosted prompt agent when the project is
  reachable, otherwise executed against the same model with identical instructions and
  flagged as a fallback so the demonstration never silently misrepresents itself.
* LOCAL   - constructed in-process with Python function tools bound to live domain data.
* A2A     - called over HTTP against this service's own JSON-RPC agent endpoint, so the
  request genuinely crosses the Agent-to-Agent protocol boundary.
"""

from __future__ import annotations

import logging
import time

import httpx

from ..config import get_settings
from ..contracts import HostingMode, NodeResult, NodeState, RunContext, ToolCall
from ..llm import extract_json, get_engine
from ..telemetry import get_tracer
from .definitions import AgentSpec
from .foundry import run_prompt_agent
from .simulation import can_simulate, simulate
from .tools import handlers_for, schemas_for

logger = logging.getLogger(__name__)

async def _run_foundry(spec: AgentSpec, prompt: str) -> tuple[str, list[ToolCall], dict[str, int], bool]:
    """Run the agent stored in Foundry. Falls back to the shared model when it is unreachable."""
    try:
        outcome = await run_prompt_agent(spec, prompt)
    except Exception as exc:
        logger.warning("Foundry execution failed for %s (%s); using fallback.", spec.name, exc)
        outcome = None

    if outcome is not None:
        text, calls, usage = outcome
        if text.strip():
            return text, calls, usage, False
        logger.warning("Foundry agent %s returned no content; using fallback.", spec.name)

    engine = get_engine()
    text, calls, usage = await engine.complete(
        instructions=spec.instructions,
        prompt=prompt,
        tools=schemas_for(spec.tools) or None,
        handlers=handlers_for(spec.tools),
    )
    return text, calls, usage, True


async def _run_a2a(spec: AgentSpec, prompt: str) -> tuple[str, list[ToolCall], dict[str, int]]:
    """Invoke the agent across a real HTTP hop using the A2A JSON-RPC envelope."""
    settings = get_settings()
    url = f"{settings.self_base_url}/a2a/{spec.name}"
    payload = {
        "jsonrpc": "2.0",
        "id": f"call-{int(time.time() * 1000)}",
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": prompt}]}},
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()

    if "error" in body:
        raise RuntimeError(f"A2A error: {body['error']}")

    result = body.get("result", {})
    text = result.get("text", "")
    usage = result.get("usage", {"prompt": 0, "completion": 0})
    calls = [
        ToolCall(
            tool_name=c.get("toolName", ""),
            arguments=c.get("arguments"),
            result=c.get("result"),
            duration_ms=c.get("durationMs", 0),
        )
        for c in result.get("toolCalls", [])
    ]
    return text, calls, usage


async def run_agent(spec: AgentSpec, prompt: str, ctx: RunContext | None = None) -> NodeResult:
    """Execute one agent and always return a valid NodeResult, even on failure.

    When no model is configured the agent is executed by the deterministic offline
    simulator instead, so the full workflow remains demonstrable with zero Azure
    services. Simulated results are tagged so the UI can label them honestly.
    """
    result = NodeResult(
        node_id=spec.node_id.value,
        agent_name=spec.name,
        hosting_mode=spec.hosting_mode,
        input=prompt,
    )
    started = time.perf_counter()
    tracer = get_tracer()

    with tracer.start_as_current_span(f"agent.{spec.name}") as span:
        span.set_attribute("agent.name", spec.name)
        span.set_attribute("agent.hosting_mode", spec.hosting_mode.value)
        span.set_attribute("agent.node_id", spec.node_id.value)
        try:
            simulated = (
                ctx is not None
                and not get_engine().available
                and can_simulate(spec.node_id.value)
            )
            if simulated:
                span.set_attribute("agent.simulated", True)
                structured = await simulate(spec.node_id.value, ctx)  # type: ignore[arg-type]
                result.structured = structured
                result.narrative = structured.get("narrative", "")
                result.state = NodeState.COMPLETED
                result.duration_ms = int((time.perf_counter() - started) * 1000)
                return result

            fallback = False
            if spec.hosting_mode is HostingMode.FOUNDRY:
                text, calls, usage, fallback = await _run_foundry(spec, prompt)
            elif spec.hosting_mode is HostingMode.A2A:
                text, calls, usage = await _run_a2a(spec, prompt)
            else:
                engine = get_engine()
                text, calls, usage = await engine.complete(
                    instructions=spec.instructions,
                    prompt=prompt,
                    tools=schemas_for(spec.tools) or None,
                    handlers=handlers_for(spec.tools),
                )

            structured = extract_json(text)
            result.structured = structured
            result.narrative = structured.get("narrative") or text.strip()[:2000]
            result.tool_calls = calls
            result.prompt_tokens = usage.get("prompt", 0)
            result.completion_tokens = usage.get("completion", 0)
            result.state = NodeState.COMPLETED
            if fallback:
                result.structured.setdefault("_executionNote", "foundry_fallback_to_shared_model")
            span.set_attribute("agent.tokens", result.total_tokens)
        except Exception as exc:
            logger.exception("Agent %s failed", spec.name)
            result.state = NodeState.FAILED
            result.error = str(exc)
            result.narrative = f"{spec.label} could not complete: {exc}"
            span.set_attribute("agent.error", str(exc))

    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result
