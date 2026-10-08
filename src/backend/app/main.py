"""FastAPI application: SSE workflow streaming, A2A agent endpoints, and static UI hosting."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agents.definitions import AGENTS, AGENTS_BY_NODE, graph_definition
from .agents.foundry import close as close_foundry
from .agents.foundry import provision_all, provisioning_status
from .agents.simulation import can_simulate, simulate
from .agents.tools import handlers_for, schemas_for
from .config import get_settings
from .contracts import EventType, RunContext
from .data import get_repository
from .knowledge import get_knowledge
from .llm import get_engine
from .localization import (
    TranslationRequest,
    TranslationResponse,
    read_translation_request,
    translate_display_texts,
)
from .orchestration.engine import REGISTRY
from .orchestration.workflow import GATE_HANDLER, build_orchestrator, signal_from_dict
from .paths import data_dir
from .telemetry import configure_telemetry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    configure_telemetry()
    provisioning: asyncio.Task | None = None
    try:
        await get_repository()
        await get_knowledge()
    except Exception:
        logger.exception("Startup warm-up encountered an issue; continuing in degraded mode.")

    # Runs in the background so a slow or unreachable project never blocks readiness.
    if get_settings().provision_foundry_agents:
        provisioning = asyncio.create_task(_store_agents_in_foundry())

    yield

    if provisioning is not None and not provisioning.done():
        provisioning.cancel()
    with contextlib.suppress(Exception, asyncio.CancelledError):
        if provisioning is not None:
            await provisioning
    with contextlib.suppress(Exception):
        await close_foundry()
    with contextlib.suppress(Exception):
        repo = await get_repository()
        await repo.close()
    with contextlib.suppress(Exception):
        knowledge = await get_knowledge()
        await knowledge.close()


async def _store_agents_in_foundry() -> None:
    try:
        status = await provision_all()
        logger.info(
            "Foundry agents stored: %d (errors: %d)",
            len(status.get("agents", [])),
            len(status.get("errors", {})),
        )
    except Exception:
        logger.exception("Foundry provisioning failed; runs fall back to the shared model.")


app = FastAPI(title="Grocery Supply Disruption Response", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
except Exception:
    logger.info("FastAPI OpenTelemetry instrumentation not enabled.")


def _load_reference_signal() -> dict[str, Any]:
    path = data_dir() / "signals.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            signals = json.load(handle)
            if signals:
                return signals[0]
    return {}


# --------------------------------------------------------------------------------------
# Core API
# --------------------------------------------------------------------------------------

@app.post(
    "/api/translate",
    response_model=TranslationResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": TranslationRequest.model_json_schema()}},
        },
    },
)
async def translate(request: Request) -> TranslationResponse:
    """Display-only en/fr/de/es translation: 1–24 texts, 12k chars each, 40k total.

    Maximum encoded body: 512,000 bytes. Translation deadline: 45 seconds,
    including the dedicated translation gate. Errors: 422 invalid request, 503 no model,
    502 invalid/provider response, 504 timeout. Originals and runs are never modified.
    """
    payload = await read_translation_request(request)
    return await translate_display_texts(payload)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    repo = await get_repository()
    knowledge = await get_knowledge()
    return {
        "status": "healthy",
        "model": settings.model_deployment,
        "openAiConfigured": settings.has_openai,
        "dataSource": repo.source,
        "knowledgeSource": knowledge.source,
        "agentCount": len(AGENTS),
    }


@app.get("/api/scenario")
async def scenario() -> dict[str, Any]:
    return {
        "signal": _load_reference_signal(),
        "graph": graph_definition(),
        "agents": [
            {
                "nodeId": spec.node_id.value,
                "name": spec.name,
                "label": spec.label,
                "description": spec.description,
                "hostingMode": spec.hosting_mode.value,
                "group": spec.group,
                "tools": spec.tools,
            }
            for spec in AGENTS
        ],
    }


@app.post("/api/runs/stream")
async def stream_run(request: Request) -> StreamingResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}

    payload = body.get("signal") or _load_reference_signal()
    signal = signal_from_dict(payload)

    ctx = RunContext(incident_id=payload.get("id", "INC-UNKNOWN"), signal=signal)
    REGISTRY.register(ctx)
    orchestrator = build_orchestrator()

    async def event_stream():
        yield _sse(
            {
                "type": EventType.RUN_STARTED.value,
                "runId": ctx.run_id,
                "incidentId": ctx.incident_id,
                "graph": graph_definition(),
                "signal": signal.to_dict(),
            }
        )
        try:
            async for event in orchestrator.execute(ctx, GATE_HANDLER):
                yield _sse(event)
        except asyncio.CancelledError:
            logger.info("Client disconnected from run %s", ctx.run_id)
            raise
        except Exception as exc:
            logger.exception("Run %s failed", ctx.run_id)
            yield _sse({"type": EventType.RUN_FAILED.value, "error": str(exc)})
        finally:
            REGISTRY.release(ctx.run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"


@app.post("/api/runs/{run_id}/decision")
async def submit_decision(run_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    option_id = body.get("optionId")
    if not option_id:
        raise HTTPException(status_code=400, detail="optionId is required")

    decision = {
        "optionId": option_id,
        "approver": body.get("approver") or "Executive Committee",
        "notes": body.get("notes") or "",
        "autoApproved": False,
    }
    if not REGISTRY.resolve(run_id, decision):
        raise HTTPException(status_code=404, detail="No run is awaiting a decision for this id")
    return {"accepted": True, "runId": run_id, "decision": decision}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    ctx = REGISTRY.context(run_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return ctx.summary()


@app.get("/api/governance")
async def governance() -> dict[str, Any]:
    settings = get_settings()
    return {
        "agents": [
            {
                "nodeId": spec.node_id.value,
                "name": spec.name,
                "hostingMode": spec.hosting_mode.value,
                "group": spec.group,
                "toolCount": len(spec.tools),
            }
            for spec in AGENTS
        ],
        "platform": {
            "model": settings.model_deployment,
            "embeddingModel": settings.embedding_deployment,
            "foundryHostedEnabled": settings.enable_foundry_hosted,
            "deliberationEnabled": settings.enable_deliberation,
            "telemetryConfigured": bool(settings.appinsights_connection),
        },
        "foundry": provisioning_status(),
    }


@app.get("/api/foundry/agents")
async def foundry_agents() -> dict[str, Any]:
    return provisioning_status()


@app.post("/api/foundry/agents/provision")
async def store_foundry_agents() -> dict[str, Any]:
    return await provision_all()


# --------------------------------------------------------------------------------------
# A2A protocol surface
# --------------------------------------------------------------------------------------

@app.get("/a2a/{agent_name}/.well-known/agent-card.json")
async def agent_card(agent_name: str) -> dict[str, Any]:
    spec = next((s for s in AGENTS if s.name == agent_name), None)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown agent")
    settings = get_settings()
    return {
        "protocolVersion": "0.2.0",
        "name": spec.name,
        "description": spec.description,
        "version": "1.0.0",
        "url": f"{settings.self_base_url}/a2a/{spec.name}",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": spec.node_id.value,
                "name": spec.label,
                "description": spec.description,
                "tags": [spec.group],
            }
        ],
    }


@app.post("/a2a/{agent_name}")
async def a2a_invoke(agent_name: str, request: Request) -> JSONResponse:
    """Minimal JSON-RPC surface implementing the A2A message/send method."""
    spec = next((s for s in AGENTS if s.name == agent_name), None)
    body = await request.json()
    request_id = body.get("id")

    if spec is None:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unknown agent"}},
            status_code=404,
        )

    if body.get("method") != "message/send":
        return JSONResponse(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unsupported method"}},
            status_code=400,
        )

    parts = (body.get("params", {}).get("message", {}) or {}).get("parts", [])
    prompt = "\n".join(p.get("text", "") for p in parts if p.get("text"))

    engine = get_engine()
    if not engine.available and can_simulate(spec.node_id.value):
        # Offline demo mode: answer from the deterministic, data-grounded simulator
        # so the A2A surface stays callable without any Azure OpenAI deployment.
        ctx = RunContext(incident_id="INC-A2A", signal=signal_from_dict(_load_reference_signal()))
        payload = await simulate(spec.node_id.value, ctx)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "text": json.dumps(payload, ensure_ascii=False),
                    "usage": {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0},
                    "toolCalls": [],
                    "simulated": True,
                },
            }
        )

    try:
        text, calls, usage = await engine.complete(
            instructions=spec.instructions,
            prompt=prompt,
            tools=schemas_for(spec.tools) or None,
            handlers=handlers_for(spec.tools),
        )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "text": text,
                    "usage": usage,
                    "toolCalls": [c.to_dict() for c in calls],
                },
            }
        )
    except Exception as exc:
        logger.exception("A2A invocation failed for %s", agent_name)
        return JSONResponse(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}},
            status_code=500,
        )


# --------------------------------------------------------------------------------------
# Static UI
# --------------------------------------------------------------------------------------

if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
else:

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Grocery Supply Disruption Response API. UI bundle not present in this build."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
