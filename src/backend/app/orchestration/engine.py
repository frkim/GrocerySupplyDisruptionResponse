"""Multi-pattern orchestration engine.

Executes a dependency graph of agents, demonstrating:
  * a sequential spine for causally dependent work
  * concurrent fan-out with a fan-in join for independent assessments
  * conditional routing that skips nodes whose precondition is unmet
  * a human-in-the-loop gate that genuinely suspends the run
  * graceful degradation, where one failed node never aborts the graph

All run state is scoped to a RunContext, so concurrent incidents cannot interfere.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..contracts import EventType, NodeResult, NodeState, RunContext

logger = logging.getLogger(__name__)

_SENTINEL = object()

NodeExecutor = Callable[[RunContext], Awaitable[NodeResult]]
NodeCondition = Callable[[RunContext], bool]


@dataclass
class Node:
    node_id: str
    executor: NodeExecutor
    depends_on: list[str] = field(default_factory=list)
    condition: NodeCondition | None = None
    is_gate: bool = False


class RunRegistry:
    """Tracks in-flight runs so an external decision can resume a suspended gate."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}

    def register(self, ctx: RunContext) -> None:
        self._runs[ctx.run_id] = {"ctx": ctx, "future": None}

    def set_gate(self, run_id: str, future: asyncio.Future) -> None:
        if run_id in self._runs:
            self._runs[run_id]["future"] = future

    def resolve(self, run_id: str, decision: dict[str, Any]) -> bool:
        entry = self._runs.get(run_id)
        if not entry:
            return False
        future = entry.get("future")
        if future is None or future.done():
            return False
        future.get_loop().call_soon_threadsafe(future.set_result, decision)
        return True

    def context(self, run_id: str) -> RunContext | None:
        entry = self._runs.get(run_id)
        return entry["ctx"] if entry else None

    def release(self, run_id: str) -> None:
        self._runs.pop(run_id, None)


REGISTRY = RunRegistry()


class Orchestrator:
    def __init__(self, nodes: list[Node]) -> None:
        self._nodes = {node.node_id: node for node in nodes}
        self._order = [node.node_id for node in nodes]

    def _waves(self) -> list[list[str]]:
        """Group nodes into dependency waves; every node in a wave runs concurrently."""
        depth: dict[str, int] = {}
        for node_id in self._order:
            node = self._nodes[node_id]
            deps = [d for d in node.depends_on if d in self._nodes]
            depth[node_id] = 0 if not deps else max(depth[d] for d in deps) + 1

        waves: dict[int, list[str]] = {}
        for node_id, level in depth.items():
            waves.setdefault(level, []).append(node_id)
        return [waves[level] for level in sorted(waves)]

    async def execute(
        self,
        ctx: RunContext,
        gate_handler: Callable[[RunContext, Callable], Awaitable[NodeResult]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield streaming events while the graph executes."""
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        task = asyncio.create_task(self._drive(ctx, emit, gate_handler))

        try:
            while True:
                event = await queue.get()
                if event is _SENTINEL:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Orchestration task ended abnormally")

    async def _drive(
        self,
        ctx: RunContext,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        gate_handler: Callable[[RunContext, Callable], Awaitable[NodeResult]] | None,
    ) -> None:
        try:
            for wave in self._waves():
                runnable: list[str] = []

                for node_id in wave:
                    node = self._nodes[node_id]

                    upstream_ok = all(
                        (ctx.get(dep) is not None and ctx.get(dep).state is not NodeState.PENDING)
                        for dep in node.depends_on
                        if dep in self._nodes
                    )
                    if node.depends_on and not upstream_ok:
                        await self._skip(ctx, emit, node_id, "upstream dependency did not run")
                        continue

                    if node.condition is not None and not node.condition(ctx):
                        await self._skip(ctx, emit, node_id, "condition not met")
                        continue

                    runnable.append(node_id)

                if not runnable:
                    continue

                gates = [n for n in runnable if self._nodes[n].is_gate]
                normal = [n for n in runnable if not self._nodes[n].is_gate]

                if normal:
                    await asyncio.gather(
                        *(self._execute_node(ctx, emit, node_id) for node_id in normal),
                        return_exceptions=True,
                    )

                for node_id in gates:
                    await self._execute_gate(ctx, emit, node_id, gate_handler)

            await emit({"type": EventType.RUN_COMPLETED.value, "summary": ctx.summary()})
        except Exception as exc:
            logger.exception("Run %s failed", ctx.run_id)
            await emit({"type": EventType.RUN_FAILED.value, "error": str(exc)})
        finally:
            await emit(_SENTINEL)

    async def _skip(self, ctx: RunContext, emit, node_id: str, reason: str) -> None:
        from ..agents.definitions import AGENTS_BY_NODE

        spec = AGENTS_BY_NODE.get(node_id)
        result = NodeResult(
            node_id=node_id,
            agent_name=spec.name if spec else node_id,
            hosting_mode=spec.hosting_mode if spec else None,  # type: ignore[arg-type]
            state=NodeState.SKIPPED,
            narrative=f"Skipped: {reason}",
        )
        ctx.record(result)
        await emit({"type": EventType.NODE_SKIPPED.value, "nodeId": node_id, "reason": reason})

    async def _execute_node(self, ctx: RunContext, emit, node_id: str) -> None:
        from ..agents.definitions import AGENTS_BY_NODE

        spec = AGENTS_BY_NODE.get(node_id)
        await emit(
            {
                "type": EventType.NODE_STARTED.value,
                "nodeId": node_id,
                "agentName": spec.name if spec else node_id,
                "hostingMode": spec.hosting_mode.value if spec else "system",
            }
        )
        try:
            result = await self._nodes[node_id].executor(ctx)
        except Exception as exc:
            logger.exception("Node %s raised", node_id)
            result = NodeResult(
                node_id=node_id,
                agent_name=spec.name if spec else node_id,
                hosting_mode=spec.hosting_mode if spec else None,  # type: ignore[arg-type]
                state=NodeState.FAILED,
                error=str(exc),
                narrative=f"Node failed: {exc}",
            )

        ctx.record(result)
        if result.state is NodeState.FAILED:
            await emit(
                {
                    "type": EventType.NODE_FAILED.value,
                    "nodeId": node_id,
                    "error": result.error,
                    "result": result.to_dict(),
                }
            )
        else:
            await emit(
                {
                    "type": EventType.NODE_COMPLETED.value,
                    "nodeId": node_id,
                    "result": result.to_dict(),
                }
            )

    async def _execute_gate(self, ctx: RunContext, emit, node_id: str, gate_handler) -> None:
        if gate_handler is None:
            await self._skip(ctx, emit, node_id, "no gate handler configured")
            return
        await emit(
            {
                "type": EventType.NODE_STARTED.value,
                "nodeId": node_id,
                "agentName": "ExecutiveApprovalGate",
                "hostingMode": "system",
            }
        )
        result = await gate_handler(ctx, emit)
        ctx.record(result)
        await emit(
            {"type": EventType.NODE_COMPLETED.value, "nodeId": node_id, "result": result.to_dict()}
        )
