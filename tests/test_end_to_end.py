"""End-to-end verification for the Grocery Supply Disruption Response solution.

Runs with no Azure dependency at all. Validates, in order:

  1. every seed dataset parses and satisfies its referential-integrity rules
  2. the agent registry, tool registry and dependency graph are internally consistent
  3. the orchestration graph is a well-formed DAG matching the declared dependencies
  4. a full workflow run executes offline, including the human-in-the-loop gate

Usage:
    python tests/test_end_to_end.py
Exit code 0 means the solution is healthy.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "src" / "backend"))

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> bool:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)
    return condition


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# 1. Seed data
# ---------------------------------------------------------------------------

REQUIRED_FILES = {
    "products.json": 18,
    "suppliers.json": 12,
    "warehouses.json": 8,
    "stores.json": 14,
    "inventory.json": 40,
    "demand-forecast.json": 16,
    "substitutes.json": 10,
    "commitments.json": 12,
    "promotions.json": 8,
    "replenishment-schedule.json": 20,
    "past-disruptions.json": 5,
    "playbooks.json": 8,
    "stakeholders.json": 12,
    "signals.json": 3,
}

REGIONS = {"NORTH", "SOUTH", "EAST", "WEST", "CENTRE"}


def load(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        FAILURES.append(f"data: missing file {name}")
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            rows = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append(f"data: {name} is not valid JSON ({exc})")
        return []
    if not isinstance(rows, list):
        FAILURES.append(f"data: {name} must be a JSON array")
        return []
    return rows


def verify_data() -> None:
    section("Seed data")
    datasets = {name: load(name) for name in REQUIRED_FILES}

    for name, minimum in REQUIRED_FILES.items():
        rows = datasets[name]
        check(len(rows) >= minimum, f"data: {name} has {len(rows)} rows, expected >= {minimum}")
        ids = [r.get("id") for r in rows]
        check(all(ids), f"data: {name} has a record without an id")
        check(len(set(ids)) == len(ids), f"data: {name} has duplicate ids")
        check(
            all(r.get("partitionKey") for r in rows),
            f"data: {name} has a record without a partitionKey",
        )

    product_ids = {r["id"] for r in datasets["products.json"] if r.get("id")}
    supplier_ids = {r["id"] for r in datasets["suppliers.json"] if r.get("id")}
    warehouse_ids = {r["id"] for r in datasets["warehouses.json"] if r.get("id")}
    store_ids = {r["id"] for r in datasets["stores.json"] if r.get("id")}

    def refs(dataset: str, rows: list[dict], field: str, universe: set[str], label: str) -> None:
        for row in rows:
            value = row.get(field)
            values = value if isinstance(value, list) else ([value] if value else [])
            for item in values:
                check(
                    item in universe,
                    f"data: {dataset} record {row.get('id')} references unknown {label} '{item}'",
                )

    refs("products", datasets["products.json"], "primarySupplierId", supplier_ids, "supplier")
    refs("products", datasets["products.json"], "alternateSupplierIds", supplier_ids, "supplier")
    refs("products", datasets["products.json"], "inputProductIds", product_ids, "product")
    refs("products", datasets["products.json"], "substituteProductIds", product_ids, "product")
    refs("substitutes", datasets["substitutes.json"], "productId", product_ids, "product")
    refs("substitutes", datasets["substitutes.json"], "substituteProductId", product_ids, "product")
    refs("stores", datasets["stores.json"], "servedByWarehouseId", warehouse_ids, "warehouse")
    refs("stores", datasets["stores.json"], "skusStocked", product_ids, "product")
    refs("inventory", datasets["inventory.json"], "productId", product_ids, "product")
    refs("demand-forecast", datasets["demand-forecast.json"], "productId", product_ids, "product")
    refs("commitments", datasets["commitments.json"], "skuId", product_ids, "product")
    refs("promotions", datasets["promotions.json"], "skuIds", product_ids, "product")
    refs(
        "replenishment-schedule",
        datasets["replenishment-schedule.json"],
        "warehouseId",
        warehouse_ids,
        "warehouse",
    )
    refs(
        "replenishment-schedule",
        datasets["replenishment-schedule.json"],
        "supplierId",
        supplier_ids,
        "supplier",
    )
    refs(
        "replenishment-schedule",
        datasets["replenishment-schedule.json"],
        "productId",
        product_ids,
        "product",
    )
    refs("signals", datasets["signals.json"], "impactedSkus", product_ids, "product")
    refs("signals", datasets["signals.json"], "affectedWarehouses", warehouse_ids, "warehouse")

    for row in datasets["inventory.json"]:
        location_type = row.get("locationType")
        universe = warehouse_ids if location_type == "warehouse" else store_ids
        check(
            location_type in {"warehouse", "store"},
            f"data: inventory {row.get('id')} has invalid locationType '{location_type}'",
        )
        check(
            row.get("locationId") in universe,
            f"data: inventory {row.get('id')} references unknown location "
            f"'{row.get('locationId')}'",
        )

    for name in ("warehouses.json", "stores.json", "inventory.json", "demand-forecast.json"):
        for row in datasets[name]:
            if "region" in row:
                check(
                    row["region"] in REGIONS,
                    f"data: {name} record {row.get('id')} has invalid region '{row['region']}'",
                )

    derived = [r for r in datasets["products.json"] if r.get("inputProductIds")]
    check(len(derived) >= 6, f"data: expected >= 6 derived products, found {len(derived)}")

    knowledge_dir = DATA / "knowledge"
    knowledge = sorted(p.name for p in knowledge_dir.glob("*.md")) if knowledge_dir.exists() else []
    check(len(knowledge) >= 8, f"data: expected >= 8 knowledge documents, found {len(knowledge)}")
    for doc in knowledge_dir.glob("*.md") if knowledge_dir.exists() else []:
        words = len(doc.read_text(encoding="utf-8").split())
        check(words >= 600, f"data: knowledge/{doc.name} has only {words} words")

    print(
        f"datasets: {len(datasets)}  products: {len(product_ids)}  "
        f"suppliers: {len(supplier_ids)}  warehouses: {len(warehouse_ids)}  "
        f"stores: {len(store_ids)}  knowledge docs: {len(knowledge)}"
    )


# ---------------------------------------------------------------------------
# 2 & 3. Agent registry and graph
# ---------------------------------------------------------------------------

def verify_graph() -> None:
    section("Agent registry and orchestration graph")
    from app.agents.definitions import AGENTS, AGENTS_BY_NODE, DEPENDENCIES, graph_definition
    from app.agents.tools import TOOL_REGISTRY
    from app.contracts import NodeId

    node_values = {n.value for n in NodeId}

    check(len(AGENTS) == 20, f"agents: expected 20 agents, found {len(AGENTS)}")
    check(
        {s.node_id.value for s in AGENTS} == node_values,
        "agents: the registry does not cover every NodeId exactly once",
    )
    check(
        len({s.name for s in AGENTS}) == len(AGENTS),
        "agents: duplicate agent names in the registry",
    )
    check(
        set(AGENTS_BY_NODE) == node_values,
        "agents: AGENTS_BY_NODE keys do not match the NodeId set",
    )

    for spec in AGENTS:
        for tool in spec.tools:
            check(tool in TOOL_REGISTRY, f"agents: {spec.name} declares unknown tool '{tool}'")
        if spec.hosting_mode.value != "system":
            check(bool(spec.instructions.strip()), f"agents: {spec.name} has no instructions")

    check(len(TOOL_REGISTRY) >= 17, f"tools: expected >= 17 tools, found {len(TOOL_REGISTRY)}")
    for name, (schema, handler) in TOOL_REGISTRY.items():
        check(
            schema.get("function", {}).get("name") == name,
            f"tools: schema name mismatch for '{name}'",
        )
        check(callable(handler), f"tools: handler for '{name}' is not callable")

    for node, deps in DEPENDENCIES.items():
        check(node in node_values, f"graph: DEPENDENCIES has unknown node '{node}'")
        for dep in deps:
            check(dep in node_values, f"graph: node '{node}' depends on unknown node '{dep}'")

    graph = graph_definition()
    check(len(graph["nodes"]) == 20, f"graph: expected 20 nodes, found {len(graph['nodes'])}")
    check(bool(graph["edges"]), "graph: no edges were produced")

    # Topological sort proves the graph is acyclic and fully reachable.
    remaining = {node: list(DEPENDENCIES.get(node, [])) for node in node_values}
    resolved: set[str] = set()
    for _ in range(len(remaining) + 1):
        ready = [n for n, d in remaining.items() if n not in resolved and set(d) <= resolved]
        if not ready:
            break
        resolved.update(ready)
    check(len(resolved) == len(remaining), "graph: the dependency graph contains a cycle")

    from app.orchestration.workflow import build_orchestrator

    orchestrator = build_orchestrator()
    waves = orchestrator._waves()  # noqa: SLF001 - deliberate white-box assertion
    check(len(waves) >= 8, f"graph: expected a deep graph, found only {len(waves)} waves")
    widest = max(len(w) for w in waves)
    check(widest >= 4, f"graph: expected a concurrent fan-out of >= 4, widest wave is {widest}")
    print(
        f"agents: {len(AGENTS)}  tools: {len(TOOL_REGISTRY)}  nodes: {len(graph['nodes'])}  "
        f"edges: {len(graph['edges'])}  waves: {len(waves)}  widest wave: {widest}"
    )


# ---------------------------------------------------------------------------
# 4. Offline workflow run
# ---------------------------------------------------------------------------

async def _run_offline() -> tuple[int, set[str]]:
    from app.contracts import EventType, RunContext
    from app.orchestration.engine import REGISTRY
    from app.orchestration.workflow import GATE_HANDLER, build_orchestrator, signal_from_dict

    signals = load("signals.json")
    payload = signals[0] if signals else {}
    ctx = RunContext(incident_id=payload.get("id", "INC-TEST"), signal=signal_from_dict(payload))
    REGISTRY.register(ctx)
    orchestrator = build_orchestrator()

    seen: set[str] = set()
    events = 0
    async for event in orchestrator.execute(ctx, GATE_HANDLER):
        events += 1
        kind = event.get("type")
        seen.add(kind)
        if kind == EventType.GATE_AWAITING.value:
            # Answer the human-in-the-loop gate exactly as the UI would.
            REGISTRY.resolve(
                event.get("runId", ctx.run_id),
                {
                    "optionId": (event.get("recommendation") or {}).get("optionId") or "A",
                    "approver": "Automated end-to-end test",
                    "notes": "Approved by the verification harness.",
                    "autoApproved": False,
                },
            )
    REGISTRY.release(ctx.run_id)
    return events, seen


def verify_run() -> None:
    section("Offline workflow run")
    from app.contracts import EventType

    async def bounded() -> tuple[int, set[str]]:
        return await asyncio.wait_for(_run_offline(), timeout=1200)

    events, seen = asyncio.run(bounded())

    check(events > 0, "run: the orchestrator produced no events")
    check(
        EventType.RUN_COMPLETED.value in seen,
        f"run: the run never completed (event types seen: {sorted(seen)})",
    )
    check(EventType.RUN_FAILED.value not in seen, "run: the orchestrator reported run_failed")
    check(
        EventType.GATE_AWAITING.value in seen,
        "run: the human-in-the-loop gate never suspended the run",
    )
    print(f"events: {events}  event types: {sorted(seen)}")


def main() -> int:
    verify_data()
    verify_graph()
    verify_run()

    section("Result")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} of {CHECKS} checks\n")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print(f"PASSED: all {CHECKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
