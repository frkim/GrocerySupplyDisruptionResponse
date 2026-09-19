"""Grocery Supply Disruption Response workflow wiring and prompt construction."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..agents.definitions import AGENTS_BY_NODE, DEPENDENCIES
from ..agents.runner import run_agent
from ..config import get_settings
from ..contracts import DisruptionSignal, EventType, HostingMode, NodeId, NodeResult, NodeState, RunContext
from .engine import REGISTRY, Node, Orchestrator

logger = logging.getLogger(__name__)


def _compact(payload: Any, limit: int = 6000) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)[:limit]


def _signal_block(ctx: RunContext) -> str:
    return f"DISRUPTION SIGNAL:\n{_compact(ctx.signal.to_dict() if ctx.signal else {})}"


def _skus(ctx: RunContext) -> list[str]:
    return list(ctx.signal.impacted_skus if ctx.signal else [])


def _product(ctx: RunContext) -> str:
    return ctx.signal.product_id if ctx.signal else ""


def _impact_preamble(ctx: RunContext) -> str:
    return (
        f"{_signal_block(ctx)}\n\n"
        f"SITUATION ASSESSMENT:\n{_compact(ctx.structured_of(NodeId.SITUATION_ASSESSMENT), 3000)}\n\n"
        f"HISTORICAL KNOWLEDGE:\n{_compact(ctx.structured_of(NodeId.HISTORICAL_KNOWLEDGE), 2500)}"
    )


def _prompt_situation(ctx: RunContext) -> str:
    return (
        f"{_signal_block(ctx)}\n\n"
        f"Assess the nationwide egg shortage for product {_product(ctx)}. Retrieve product, supplier, "
        "warehouse inventory, store inventory, dependent products, and replenishment schedule. Produce the situation assessment JSON."
    )


def _prompt_historical(ctx: RunContext) -> str:
    return (
        f"{_signal_block(ctx)}\n\n"
        f"SITUATION ASSESSMENT:\n{_compact(ctx.structured_of(NodeId.SITUATION_ASSESSMENT), 3500)}\n\n"
        "Retrieve prior HPAI egg shortages, playbooks, and knowledge passages. Produce the historical knowledge JSON."
    )


def _prompt_demand(ctx: RunContext) -> str:
    return f"{_impact_preamble(ctx)}\n\nImpacted SKUs: {_skus(ctx)}\nQuantify demand surge, promotional uplift, and exposed store clusters. Produce the demand forecast JSON."


def _prompt_inventory(ctx: RunContext) -> str:
    return f"{_impact_preamble(ctx)}\n\nAffected warehouses: {ctx.signal.affected_warehouses if ctx.signal else []}\nAssess DC and store inventory, inbound risk, and transfer opportunities. Produce the network inventory JSON."


def _prompt_financial(ctx: RunContext) -> str:
    return f"{_impact_preamble(ctx)}\n\nImpacted SKUs: {_skus(ctx)}\nQuantify four-week financial exposure in EUR. Produce the financial impact JSON."


def _prompt_store(ctx: RunContext) -> str:
    return f"{_impact_preamble(ctx)}\n\nImpacted SKUs: {_skus(ctx)}\nAssess store, shelf, customer, commitment, promotion, and fairness exposure. Produce the store impact JSON."


def _prompt_synthesis(ctx: RunContext) -> str:
    blocks = []
    for node_id, label in (
        (NodeId.DEMAND_FORECAST, "DEMAND FORECAST"),
        (NodeId.NETWORK_INVENTORY, "NETWORK INVENTORY"),
        (NodeId.FINANCIAL_IMPACT, "FINANCIAL IMPACT"),
        (NodeId.STORE_IMPACT, "STORE AND CUSTOMER IMPACT"),
    ):
        result = ctx.get(node_id)
        blocks.append(f"{label}:\n{_compact(result.structured, 3000)}" if result and result.state is NodeState.COMPLETED else f"{label}: NOT AVAILABLE")
    return f"{_signal_block(ctx)}\n\n" + "\n\n".join(blocks) + "\n\nConsolidate the impact picture. Produce the impact synthesis JSON."


def _prompt_planner(ctx: RunContext) -> str:
    return (
        f"{_signal_block(ctx)}\n\n"
        f"IMPACT SYNTHESIS:\n{_compact(ctx.structured_of(NodeId.IMPACT_SYNTHESIS), 4000)}\n\n"
        f"HISTORICAL ACTIONS:\n{_compact(ctx.structured_of(NodeId.HISTORICAL_KNOWLEDGE).get('mostEffectiveActions', []), 1500)}\n\n"
        "Create exactly four response options A-D using the fixed levers in your instructions. Produce the response planner JSON."
    )


def _validation_prompt(ctx: RunContext, focus: str) -> str:
    return (
        f"{_signal_block(ctx)}\n\n"
        f"IMPACT SYNTHESIS:\n{_compact(ctx.structured_of(NodeId.IMPACT_SYNTHESIS), 2500)}\n\n"
        f"RESPONSE OPTIONS:\n{_compact(ctx.structured_of(NodeId.RESPONSE_PLANNER).get('options', []), 7000)}\n\n"
        f"{focus} Assess options A, B, C, and D. Produce your validation JSON."
    )


def _prompt_evaluation(ctx: RunContext) -> str:
    blocks = [f"RESPONSE OPTIONS:\n{_compact(ctx.structured_of(NodeId.RESPONSE_PLANNER).get('options', []), 7000)}"]
    for node_id, label in (
        (NodeId.SOURCING_PROCUREMENT, "SOURCING AND PROCUREMENT"),
        (NodeId.ALLOCATION_FAIRNESS, "ALLOCATION AND FAIR SHARE"),
        (NodeId.SUBSTITUTION_ASSORTMENT, "SUBSTITUTION AND ASSORTMENT"),
        (NodeId.PRICING_COMPLIANCE, "PRICING AND COMPLIANCE"),
        (NodeId.LOGISTICS_COLD_CHAIN, "LOGISTICS AND COLD CHAIN"),
    ):
        result = ctx.get(node_id)
        blocks.append(f"{label} ASSESSMENT:\n{_compact(result.structured, 2500)}" if result and result.state is NodeState.COMPLETED else f"{label} ASSESSMENT: NOT AVAILABLE")
    return "\n\n".join(blocks) + "\n\nScore options on financial, operational, customer, compliance, and sustainability dimensions. Produce the scenario evaluation JSON."


def _prompt_deliberation(ctx: RunContext) -> str:
    return f"SCENARIO EVALUATION:\n{_compact(ctx.structured_of(NodeId.SCENARIO_EVALUATION), 7000)}\n\nThe leading options are close. Debate them and converge. Produce the deliberation JSON."


def _prompt_store_ops(ctx: RunContext) -> str:
    return (
        f"APPROVED DECISION:\n{_compact(ctx.decision or {}, 1200)}\n\n"
        f"EVALUATION:\n{_compact(ctx.structured_of(NodeId.SCENARIO_EVALUATION), 3500)}\n\n"
        "Create the owned store and warehouse execution plan. Produce the store operations JSON."
    )


def _prompt_customer_comm(ctx: RunContext) -> str:
    return (
        f"APPROVED DECISION:\n{_compact(ctx.decision or {}, 1200)}\n\n"
        f"EVALUATION:\n{_compact(ctx.structured_of(NodeId.SCENARIO_EVALUATION), 3500)}\n\n"
        "Create customer, colleague, franchise/B2B, and media communications. Produce the customer communication JSON."
    )


def _prompt_briefing(ctx: RunContext) -> str:
    return (
        f"{_signal_block(ctx)}\n\n"
        f"IMPACT SYNTHESIS:\n{_compact(ctx.structured_of(NodeId.IMPACT_SYNTHESIS), 2500)}\n\n"
        f"EVALUATION:\n{_compact(ctx.structured_of(NodeId.SCENARIO_EVALUATION), 4500)}\n\n"
        f"DECISION:\n{_compact(ctx.decision or {}, 1000)}\n\n"
        f"STORE OPERATIONS:\n{_compact(ctx.structured_of(NodeId.STORE_OPERATIONS), 2500)}\n\n"
        f"CUSTOMER COMMUNICATION:\n{_compact(ctx.structured_of(NodeId.CUSTOMER_COMMUNICATION), 2500)}\n\n"
        "Produce the executive briefing JSON."
    )


_PROMPTS = {
    NodeId.SITUATION_ASSESSMENT: _prompt_situation,
    NodeId.HISTORICAL_KNOWLEDGE: _prompt_historical,
    NodeId.DEMAND_FORECAST: _prompt_demand,
    NodeId.NETWORK_INVENTORY: _prompt_inventory,
    NodeId.FINANCIAL_IMPACT: _prompt_financial,
    NodeId.STORE_IMPACT: _prompt_store,
    NodeId.IMPACT_SYNTHESIS: _prompt_synthesis,
    NodeId.RESPONSE_PLANNER: _prompt_planner,
    NodeId.SOURCING_PROCUREMENT: lambda c: _validation_prompt(c, "Validate supplier capacity, import feasibility, qualification, pricing, and procurement risk."),
    NodeId.ALLOCATION_FAIRNESS: lambda c: _validation_prompt(c, "Validate fair-share allocation, per-customer purchase limits, regional equity, and service protection."),
    NodeId.SUBSTITUTION_ASSORTMENT: lambda c: _validation_prompt(c, "Validate substitute formats, liquid egg, plant-based replacer, own-brand reformulation, and assortment actions."),
    NodeId.PRICING_COMPLIANCE: lambda c: _validation_prompt(c, "Validate pricing, promotion cancellation, consumer-protection, labelling, and food-safety compliance."),
    NodeId.LOGISTICS_COLD_CHAIN: lambda c: _validation_prompt(c, "Validate chilled logistics, warehouse capacity, transfers, inbound doors, shelf-life, and transport feasibility."),
    NodeId.SCENARIO_EVALUATION: _prompt_evaluation,
    NodeId.DELIBERATION: _prompt_deliberation,
    NodeId.STORE_OPERATIONS: _prompt_store_ops,
    NodeId.CUSTOMER_COMMUNICATION: _prompt_customer_comm,
    NodeId.EXECUTIVE_BRIEFING: _prompt_briefing,
}


def _agent_executor(node_id: NodeId):
    async def execute(ctx: RunContext) -> NodeResult:
        spec = AGENTS_BY_NODE[node_id.value]
        return await run_agent(spec, _PROMPTS[node_id](ctx), ctx)
    return execute


def _derive_severity(signal: DisruptionSignal) -> str:
    score = 0
    if signal.depletion_days_min <= 5:
        score += 3
    elif signal.depletion_days_min <= 10:
        score += 2
    elif signal.depletion_days_min <= 21:
        score += 1
    if signal.supply_shortfall_pct >= 35:
        score += 3
    elif signal.supply_shortfall_pct >= 20:
        score += 2
    elif signal.supply_shortfall_pct >= 10:
        score += 1
    if signal.demand_surge_pct >= 35:
        score += 3
    elif signal.demand_surge_pct >= 20:
        score += 2
    elif signal.demand_surge_pct >= 10:
        score += 1
    if score >= 7:
        return "critical"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


async def _normalize_signal(ctx: RunContext) -> NodeResult:
    spec = AGENTS_BY_NODE[NodeId.SIGNAL_NORMALIZER.value]
    signal = ctx.signal
    result = NodeResult(node_id=spec.node_id.value, agent_name=spec.name, hosting_mode=HostingMode.SYSTEM, state=NodeState.COMPLETED)
    if signal is None:
        result.state = NodeState.FAILED
        result.error = "no signal supplied"
        return result
    severity = _derive_severity(signal)
    result.structured = {
        "incidentId": ctx.incident_id,
        "productId": signal.product_id,
        "productName": signal.product_name,
        "category": signal.category,
        "supplierId": signal.supplier_id,
        "confidence": signal.confidence,
        "depletionWindowDays": [signal.depletion_days_min, signal.depletion_days_max],
        "supplyShortfallPct": signal.supply_shortfall_pct,
        "demandSurgePct": signal.demand_surge_pct,
        "impactedSkuCount": len(signal.impacted_skus),
        "affectedRegions": signal.affected_regions,
        "affectedWarehouses": signal.affected_warehouses,
        "rootCause": signal.root_cause,
        "initialSeverity": severity,
        "source": signal.source,
    }
    result.narrative = (
        f"Signal accepted from {signal.source} at confidence {signal.confidence:.2f}. "
        f"{signal.product_name} ({signal.product_id}) depletes in {signal.depletion_days_min}-{signal.depletion_days_max} days, "
        f"with {signal.supply_shortfall_pct:.1f}% supply shortfall and {signal.demand_surge_pct:.1f}% demand surge across "
        f"{len(signal.affected_warehouses)} warehouses. Initial severity classified as {severity}."
    )
    return result


def _make_gate_handler():
    async def handle(ctx: RunContext, emit) -> NodeResult:
        settings = get_settings()
        spec = AGENTS_BY_NODE[NodeId.EXECUTIVE_GATE.value]
        evaluation = ctx.structured_of(NodeId.SCENARIO_EVALUATION)
        deliberation = ctx.structured_of(NodeId.DELIBERATION)
        options = evaluation.get("options", [])
        recommended = deliberation.get("convergedRecommendationId") or evaluation.get("recommendedOptionId") or (options[0].get("optionId") if options else "A")
        rationale = deliberation.get("narrative") or evaluation.get("rationale") or "Highest weighted score across financial, operational, customer, compliance, and sustainability dimensions."

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        REGISTRY.set_gate(ctx.run_id, future)
        await emit({"type": EventType.GATE_AWAITING.value, "nodeId": spec.node_id.value, "runId": ctx.run_id, "options": options, "recommendation": {"optionId": recommended, "rationale": rationale}})

        result = NodeResult(node_id=spec.node_id.value, agent_name=spec.name, hosting_mode=HostingMode.SYSTEM)
        try:
            decision = await asyncio.wait_for(future, timeout=settings.gate_timeout)
        except asyncio.TimeoutError:
            decision = {"optionId": recommended, "approver": "Auto-approved (gate timeout)", "notes": "No human decision was recorded before the gate expired.", "autoApproved": True}

        ctx.decision = decision
        result.state = NodeState.COMPLETED
        result.structured = {
            "approvedOptionId": decision.get("optionId"),
            "approver": decision.get("approver"),
            "notes": decision.get("notes"),
            "autoApproved": decision.get("autoApproved", False),
            "recommendationFollowed": decision.get("optionId") == recommended,
        }
        result.narrative = f"Option {decision.get('optionId')} approved by {decision.get('approver')}."
        return result
    return handle


def build_orchestrator() -> Orchestrator:
    settings = get_settings()

    def deliberation_condition(ctx: RunContext) -> bool:
        if not settings.enable_deliberation:
            return False
        evaluation = ctx.structured_of(NodeId.SCENARIO_EVALUATION)
        if evaluation.get("closeCall") is True:
            return True
        scores = sorted((float(o.get("totalScore", 0) or 0) for o in evaluation.get("options", [])), reverse=True)
        return len(scores) >= 2 and (scores[0] - scores[1]) <= 8.0

    nodes = [Node(NodeId.SIGNAL_NORMALIZER.value, _normalize_signal, depends_on=[])]
    for node_id in (
        NodeId.SITUATION_ASSESSMENT,
        NodeId.HISTORICAL_KNOWLEDGE,
        NodeId.DEMAND_FORECAST,
        NodeId.NETWORK_INVENTORY,
        NodeId.FINANCIAL_IMPACT,
        NodeId.STORE_IMPACT,
        NodeId.IMPACT_SYNTHESIS,
        NodeId.RESPONSE_PLANNER,
        NodeId.SOURCING_PROCUREMENT,
        NodeId.ALLOCATION_FAIRNESS,
        NodeId.SUBSTITUTION_ASSORTMENT,
        NodeId.PRICING_COMPLIANCE,
        NodeId.LOGISTICS_COLD_CHAIN,
        NodeId.SCENARIO_EVALUATION,
    ):
        nodes.append(Node(node_id.value, _agent_executor(node_id), depends_on=DEPENDENCIES.get(node_id.value, [])))
    nodes.append(Node(NodeId.DELIBERATION.value, _agent_executor(NodeId.DELIBERATION), depends_on=DEPENDENCIES.get(NodeId.DELIBERATION.value, []), condition=deliberation_condition))
    nodes.append(Node(NodeId.EXECUTIVE_GATE.value, _normalize_signal, depends_on=DEPENDENCIES.get(NodeId.EXECUTIVE_GATE.value, []), is_gate=True))
    for node_id in (NodeId.STORE_OPERATIONS, NodeId.CUSTOMER_COMMUNICATION, NodeId.EXECUTIVE_BRIEFING):
        nodes.append(Node(node_id.value, _agent_executor(node_id), depends_on=DEPENDENCIES.get(node_id.value, [])))
    return Orchestrator(nodes)


def signal_from_dict(payload: dict[str, Any]) -> DisruptionSignal:
    return DisruptionSignal(
        product_id=payload.get("productId", ""),
        product_name=payload.get("productName", ""),
        category=payload.get("category", ""),
        supplier_id=payload.get("supplierId", ""),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        depletion_days_min=int(payload.get("depletionDaysMin", 0) or 0),
        depletion_days_max=int(payload.get("depletionDaysMax", 0) or 0),
        supply_shortfall_pct=float(payload.get("supplyShortfallPct", 0.0) or 0.0),
        demand_surge_pct=float(payload.get("demandSurgePct", 0.0) or 0.0),
        impacted_skus=list(payload.get("impactedSkus") or []),
        affected_regions=list(payload.get("affectedRegions") or []),
        affected_warehouses=list(payload.get("affectedWarehouses") or []),
        root_cause=payload.get("rootCause", ""),
        source=payload.get("source", "databricks-stub"),
        detected_at=payload.get("detectedAt", ""),
    )


GATE_HANDLER = _make_gate_handler()
