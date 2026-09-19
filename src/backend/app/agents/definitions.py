"""Agent registry for the grocery egg-shortage response domain."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import HostingMode, NodeId


@dataclass(frozen=True)
class AgentSpec:
    node_id: NodeId
    name: str
    label: str
    description: str
    hosting_mode: HostingMode
    group: str
    row: int
    col: int
    instructions: str = ""
    tools: list[str] = field(default_factory=list)


_COMMON = (
    "You support Vivalis Retail Group, a national grocery retail group, during a nationwide "
    "egg shortage caused by highly pathogenic avian influenza. Ground every claim in tool "
    "output; do not invent figures, capacities, prices, dates, stores, warehouses, suppliers, "
    "or regulatory constraints. If evidence is missing, say so explicitly. All monetary values "
    "are in EUR. Respond with a single valid JSON object and no Markdown fences."
)


def _instruction(role: str, tool_rule: str, contract: str, extra: str = "") -> str:
    return f"""{_COMMON}

You are the {role}.
{tool_rule}
{extra}
Return JSON with exactly this contract and no extra keys:
{contract}"""


AGENTS: list[AgentSpec] = [
    AgentSpec(
        NodeId.SIGNAL_NORMALIZER,
        "ShortageSignalNormalizer",
        "Signal Normalizer",
        "Normalizes the inbound grocery shortage signal and computes initial severity from cover, shortfall, and demand surge.",
        HostingMode.SYSTEM,
        "detection",
        0,
        2,
        instructions=_instruction(
            "Shortage Signal Normalizer",
            "Use the inbound signal only; no tools are available.",
            '''{
  "incidentId": string,
  "productId": string,
  "productName": string,
  "category": string,
  "supplierId": string,
  "confidence": number,
  "depletionWindowDays": [number, number],
  "supplyShortfallPct": number,
  "demandSurgePct": number,
  "impactedSkuCount": number,
  "affectedRegions": [string],
  "affectedWarehouses": [string],
  "rootCause": string,
  "initialSeverity": "low" | "medium" | "high" | "critical",
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.SITUATION_ASSESSMENT,
        "SituationAssessmentAgent",
        "Situation Assessment",
        "Establishes the egg shortage scope, product exposure, supplier status, DC cover, store shelf impact, and root cause.",
        HostingMode.FOUNDRY,
        "situational",
        1,
        2,
        tools=["get_product", "get_supplier", "get_warehouse_inventory", "get_store_inventory", "get_dependent_products", "get_replenishment_schedule"],
        instructions=_instruction(
            "Situation Assessment Agent",
            "Before answering, call get_product, get_supplier, get_warehouse_inventory, get_store_inventory, get_dependent_products, and get_replenishment_schedule for the disrupted product.",
            '''{
  "situationTitle": string,
  "rootCauseAnalysis": string,
  "primaryProduct": {"productId": string, "name": string, "category": string, "strategicTier": string},
  "supplierStatus": {"supplierId": string, "name": string, "avianInfluenzaStatus": string, "availableCapacityCasesPerWeek": number, "leadTimeDays": number},
  "warehouseExposure": [{"warehouseId": string, "region": string, "availableCases": number, "daysOfCover": number, "inTransitCases": number}],
  "storeExposure": [{"locationId": string, "region": string, "availableCases": number, "daysOfCover": number}],
  "dependentProducts": [{"productId": string, "name": string, "category": string, "eggContentUnitsPerCase": number}],
  "replenishmentRisks": [{"id": string, "warehouseId": string, "confirmedCases": number, "shortfallCases": number, "status": string}],
  "severity": "low" | "medium" | "high" | "critical",
  "confidence": number,
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.HISTORICAL_KNOWLEDGE,
        "HistoricalKnowledgeAgent",
        "Historical Knowledge",
        "Retrieves HPAI precedent, playbooks, and corporate knowledge relevant to egg shortage response.",
        HostingMode.FOUNDRY,
        "situational",
        2,
        2,
        tools=["get_past_disruptions", "get_playbooks", "search_knowledge"],
        instructions=_instruction(
            "Historical Knowledge Agent",
            "Before answering, call get_past_disruptions, get_playbooks, and search_knowledge with an egg shortage/HPAI query.",
            '''{
  "hasPrecedent": boolean,
  "precedents": [{"id": string, "title": string, "date": string, "durationDays": number, "peakShortfallPct": number, "revenueLostEur": number}],
  "mitigationsPreviouslyApplied": [{"action": string, "outcome": string, "effectivenessScore": number, "costEur": number}],
  "relevantPlaybooks": [{"id": string, "name": string, "category": string, "leadTimeDays": number, "typicalCostEur": number}],
  "mostEffectiveActions": [string],
  "lessonsLearned": [string],
  "citedSources": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.DEMAND_FORECAST,
        "DemandForecastAgent",
        "Demand Forecast",
        "Quantifies baseline versus surge demand by SKU and region for the shortage horizon.",
        HostingMode.LOCAL,
        "impact",
        3,
        0,
        tools=["get_demand_forecast", "get_promotions_for_skus", "get_stores_for_skus"],
        instructions=_instruction(
            "Demand Forecast Agent",
            "Before answering, call get_demand_forecast for impacted SKUs, get_promotions_for_skus, and get_stores_for_skus.",
            '''{
  "forecastHorizonWeeks": number,
  "skuDemand": [{"skuId": string, "region": string, "baselineWeeklyCases": number, "currentWeeklyCases": number, "surgePct": number, "forecastWeek1Cases": number, "forecastWeek2Cases": number, "forecastWeek3Cases": number, "forecastWeek4Cases": number, "confidence": number}],
  "promotionDrivers": [{"promotionId": string, "name": string, "status": string, "expectedUpliftPct": number, "forecastIncrementalCases": number}],
  "storeClustersAtRisk": [{"clusterId": string, "region": string, "format": string, "storeCount": number, "currentDaysOfCover": number, "shelfAvailabilityPct": number}],
  "totalBaselineWeeklyCases": number,
  "totalCurrentWeeklyCases": number,
  "weightedDemandSurgePct": number,
  "assumptions": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.NETWORK_INVENTORY,
        "NetworkInventoryAgent",
        "Network Inventory",
        "Assesses warehouse and store stock, cover, transfer feasibility, and inbound replenishment risk.",
        HostingMode.LOCAL,
        "impact",
        3,
        1,
        tools=["get_warehouse_inventory", "get_store_inventory", "get_warehouses", "get_replenishment_schedule"],
        instructions=_instruction(
            "Network Inventory Agent",
            "Before answering, call get_warehouse_inventory, get_store_inventory, get_warehouses for affected warehouses, and get_replenishment_schedule.",
            '''{
  "networkCoverSummary": {"availableWarehouseCases": number, "availableStoreCases": number, "lowestCoverDays": number, "expiryRiskCases": number},
  "warehousePositions": [{"warehouseId": string, "region": string, "availableCases": number, "daysOfCover": number, "safetyStockCases": number, "chilledUtilizationPct": number}],
  "storePositions": [{"locationId": string, "region": string, "availableCases": number, "daysOfCover": number}],
  "inboundRisk": [{"id": string, "warehouseId": string, "orderedCases": number, "confirmedCases": number, "shortfallCases": number, "status": string}],
  "transferOpportunities": [{"fromWarehouseId": string, "toWarehouseId": string, "leadTimeHours": number, "rationale": string}],
  "constraints": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.FINANCIAL_IMPACT,
        "FinancialImpactAgent",
        "Financial Impact",
        "Quantifies revenue, margin, penalty, promotion, and sourcing cost exposure from the egg shortage.",
        HostingMode.A2A,
        "impact",
        3,
        3,
        tools=["get_product", "get_dependent_products", "get_demand_forecast", "get_commitments_for_skus", "get_promotions_for_skus"],
        instructions=_instruction(
            "Financial Impact Agent",
            "Before answering, call get_product, get_dependent_products, get_demand_forecast, get_commitments_for_skus, and get_promotions_for_skus.",
            '''{
  "revenueAtRiskEur": number,
  "marginImpactEur": number,
  "penaltyExposureEur": number,
  "promotionCancellationOrWasteEur": number,
  "incrementalSourcingCostEur": number,
  "totalExposureEur": number,
  "exposureBySku": [{"skuId": string, "name": string, "revenueAtRiskEur": number, "marginImpactEur": number}],
  "exposureByRegion": [{"region": string, "revenueAtRiskEur": number}],
  "assumptions": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.STORE_IMPACT,
        "StoreImpactAgent",
        "Store & Customer Impact",
        "Assesses shelf availability, store formats, customer friction, and fairness implications.",
        HostingMode.A2A,
        "impact",
        3,
        4,
        tools=["get_store_inventory", "get_stores_for_skus", "get_commitments_for_skus", "get_promotions_for_skus"],
        instructions=_instruction(
            "Store and Customer Impact Agent",
            "Before answering, call get_store_inventory, get_stores_for_skus, get_commitments_for_skus, and get_promotions_for_skus for impacted SKUs.",
            '''{
  "storeClustersAffected": [{"clusterId": string, "region": string, "format": string, "storeCount": number, "daysOfCover": number, "shelfAvailabilityPct": number}],
  "estimatedStoresWithEmptyShelves": number,
  "customerRiskLevel": "low" | "medium" | "high" | "severe",
  "commitmentsAtRisk": [{"commitmentId": string, "skuId": string, "weeklyCases": number, "currentServiceLevelPct": number, "priority": string}],
  "promotionsImpacted": [{"promotionId": string, "name": string, "status": string, "regions": [string], "cancellationCostEur": number}],
  "fairnessConcerns": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.IMPACT_SYNTHESIS,
        "ImpactSynthesisAgent",
        "Impact Synthesis",
        "Consolidates demand, inventory, financial, and store/customer findings into one exposure picture.",
        HostingMode.FOUNDRY,
        "impact",
        4,
        2,
        instructions=_instruction(
            "Impact Synthesis Agent",
            "Use the upstream impact assessments supplied in the prompt; no tools are available.",
            '''{
  "overallSeverity": "low" | "medium" | "high" | "critical",
  "urgencyDays": number,
  "consolidatedExposureEur": number,
  "shelfAvailabilityRiskPct": number,
  "totalCurrentWeeklyDemandCases": number,
  "availableNetworkCases": number,
  "criticalRegions": [string],
  "headlineFindings": [string],
  "decisionDrivers": [string],
  "gapsInAnalysis": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.RESPONSE_PLANNER,
        "ResponsePlannerAgent",
        "Response Planner",
        "Builds the four fixed strategic response options A-D for the egg shortage.",
        HostingMode.FOUNDRY,
        "remediation",
        5,
        2,
        tools=["find_alternative_suppliers", "get_playbooks", "get_substitutes", "get_warehouses", "get_promotions_for_skus", "get_replenishment_schedule"],
        instructions=_instruction(
            "Response Planner Agent",
            "Before answering, call find_alternative_suppliers, get_playbooks, get_substitutes, get_warehouses, get_promotions_for_skus, and get_replenishment_schedule.",
            '''{
  "options": [
    {"optionId": "A", "title": string, "description": string, "leverPrimary": "sourcing", "costEur": number, "timeToImplementDays": number, "riskLevel": "low" | "medium" | "high", "customerImpact": string, "shelfAvailabilityRecoveryPct": number, "expectedOutcome": string, "keyActions": [string], "dependencies": [string]},
    {"optionId": "B", "title": string, "description": string, "leverPrimary": "allocation", "costEur": number, "timeToImplementDays": number, "riskLevel": "low" | "medium" | "high", "customerImpact": string, "shelfAvailabilityRecoveryPct": number, "expectedOutcome": string, "keyActions": [string], "dependencies": [string]},
    {"optionId": "C", "title": string, "description": string, "leverPrimary": "substitution", "costEur": number, "timeToImplementDays": number, "riskLevel": "low" | "medium" | "high", "customerImpact": string, "shelfAvailabilityRecoveryPct": number, "expectedOutcome": string, "keyActions": [string], "dependencies": [string]},
    {"optionId": "D", "title": string, "description": string, "leverPrimary": "demand-shaping", "costEur": number, "timeToImplementDays": number, "riskLevel": "low" | "medium" | "high", "customerImpact": string, "shelfAvailabilityRecoveryPct": number, "expectedOutcome": string, "keyActions": [string], "dependencies": [string]}
  ],
  "recommendedForValidation": [string],
  "planningAssumptions": [string],
  "narrative": string
}''',
            "Option A must lead with emergency import plus alternate co-ops. Option B must lead with fair-share warehouse allocation plus per-customer purchase limits. Option C must lead with substitute formats, liquid egg and plant-based replacer, and own-brand bakery reformulation. Option D must lead with cancelling promotions, de-listing low-priority derived SKUs, managing price, and customer communications. Emit exactly four options A, B, C, and D.",
        ),
    ),
    AgentSpec(
        NodeId.SOURCING_PROCUREMENT,
        "SourcingProcurementAgent",
        "Sourcing & Procurement",
        "Validates supplier capacity, qualification, import feasibility, price, and sourcing risk for each option.",
        HostingMode.A2A,
        "validation",
        6,
        0,
        tools=["get_product", "get_supplier", "find_alternative_suppliers", "get_playbooks"],
        instructions=_instruction(
            "Sourcing and Procurement Agent",
            "Before answering, call get_product, get_supplier, find_alternative_suppliers, and get_playbooks with category sourcing.",
            '''{
  "assessments": [{"optionId": string, "feasible": boolean, "capacityCasesPerWeek": number, "leadTimeDays": number, "qualificationRisk": string, "pricePremiumPct": number, "supplierRisks": [string], "recommendations": [string]}],
  "preferredOptionId": string,
  "blockingIssues": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.ALLOCATION_FAIRNESS,
        "AllocationFairnessAgent",
        "Allocation & Fair Share",
        "Validates fair-share DC allocation, store prioritisation, purchase limits, and equity across regions/formats.",
        HostingMode.LOCAL,
        "validation",
        6,
        1,
        tools=["get_warehouse_inventory", "get_store_inventory", "get_stores_for_skus", "get_warehouses", "get_playbooks"],
        instructions=_instruction(
            "Allocation and Fair Share Agent",
            "Before answering, call get_warehouse_inventory, get_store_inventory, get_stores_for_skus, get_warehouses, and get_playbooks with category allocation.",
            '''{
  "assessments": [{"optionId": string, "fairnessScore": number, "serviceProtectionScore": number, "purchaseLimitRequired": boolean, "regionalTradeoffs": [string], "operationalConcerns": [string], "recommendations": [string]}],
  "preferredOptionId": string,
  "minimumRules": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.SUBSTITUTION_ASSORTMENT,
        "SubstitutionAssortmentAgent",
        "Substitution & Assortment",
        "Validates substitute SKUs, liquid egg, plant-based replacers, derived SKU reformulation, and assortment changes.",
        HostingMode.LOCAL,
        "validation",
        6,
        2,
        tools=["get_product", "get_dependent_products", "get_substitutes", "get_playbooks", "get_demand_forecast"],
        instructions=_instruction(
            "Substitution and Assortment Agent",
            "Before answering, call get_product, get_dependent_products, get_substitutes, get_playbooks with category substitution, and get_demand_forecast.",
            '''{
  "assessments": [{"optionId": string, "substitutionCoverageCasesPerWeek": number, "customerAcceptanceScore": number, "reformulationLeadTimeDays": number, "labellingChanges": [string], "assortmentActions": [string], "concerns": [string]}],
  "preferredOptionId": string,
  "recommendedSubstitutes": [{"productId": string, "substituteProductId": string, "substitutionType": string, "conversionRatio": number}],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.PRICING_COMPLIANCE,
        "PricingComplianceAgent",
        "Pricing & Compliance",
        "Validates consumer-protection, pricing, promotion, labelling, and food-safety constraints.",
        HostingMode.A2A,
        "validation",
        6,
        3,
        tools=["get_promotions_for_skus", "get_substitutes", "get_playbooks", "search_knowledge"],
        instructions=_instruction(
            "Pricing and Compliance Agent",
            "Before answering, call get_promotions_for_skus, get_substitutes, get_playbooks with category pricing, and search_knowledge for pricing and avian influenza regulation.",
            '''{
  "assessments": [{"optionId": string, "compliant": boolean, "complianceScore": number, "pricingRisk": string, "promotionRisk": string, "labellingImpact": string, "foodSafetyNotes": [string], "requiredApprovals": [string], "blockingIssues": [string]}],
  "preferredOptionId": string,
  "citedSources": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.LOGISTICS_COLD_CHAIN,
        "LogisticsColdChainAgent",
        "Logistics & Cold Chain",
        "Validates chilled capacity, inbound doors, transfers, shelf life, transport feasibility, and cold-chain risk.",
        HostingMode.A2A,
        "validation",
        6,
        4,
        tools=["get_warehouses", "get_replenishment_schedule", "get_warehouse_inventory", "get_supplier"],
        instructions=_instruction(
            "Logistics and Cold Chain Agent",
            "Before answering, call get_warehouses, get_replenishment_schedule, get_warehouse_inventory, and get_supplier for relevant inbound suppliers.",
            '''{
  "assessments": [{"optionId": string, "logisticsFeasible": boolean, "coldChainRiskScore": number, "inboundDoorPressure": string, "transferLeadTimeHours": number, "shelfLifeRisk": string, "transportConstraints": [string], "recommendations": [string]}],
  "preferredOptionId": string,
  "networkBottlenecks": [string],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.SCENARIO_EVALUATION,
        "ScenarioEvaluationAgent",
        "Scenario Evaluation",
        "Scores options A-D across financial, operational, customer, compliance, and sustainability dimensions.",
        HostingMode.FOUNDRY,
        "decision",
        7,
        2,
        instructions=_instruction(
            "Scenario Evaluation Agent",
            "Use the response options and all five validation assessments supplied in the prompt; no tools are available.",
            '''{
  "options": [{"optionId": string, "title": string, "description": string, "leverPrimary": string, "costEur": number, "timeToImplementDays": number, "riskLevel": string, "customerImpact": string, "shelfAvailabilityRecoveryPct": number, "expectedOutcome": string, "scores": {"financial": number, "operational": number, "customer": number, "compliance": number, "sustainability": number}, "totalScore": number, "blockingIssues": [string]}],
  "ranking": [string],
  "recommendedOptionId": string,
  "closeCall": boolean,
  "rationale": string,
  "narrative": string
}''',
            "Score each dimension from 0 to 100 and compute totalScore as a weighted 0 to 100 score. The only score keys are financial, operational, customer, compliance, sustainability. Include all four options A, B, C, and D. Set closeCall to true when the top two total scores are within 8 points.",
        ),
    ),
    AgentSpec(
        NodeId.DELIBERATION,
        "DeliberationAgent",
        "Deliberation",
        "Runs structured debate on close-call options before executive approval.",
        HostingMode.FOUNDRY,
        "decision",
        8,
        2,
        instructions=_instruction(
            "Deliberation Agent",
            "Use the scenario evaluation supplied in the prompt; no tools are available.",
            '''{
  "contendingOptions": [string],
  "argumentsFor": [{"optionId": string, "perspective": string, "argument": string}],
  "argumentsAgainst": [{"optionId": string, "perspective": string, "argument": string}],
  "decisiveFactors": [string],
  "convergedRecommendationId": string,
  "dissentingView": string,
  "narrative": string
}''',
            "Debate from sourcing, allocation, store operations, customer, finance, compliance, and sustainability perspectives before converging.",
        ),
    ),
    AgentSpec(
        NodeId.EXECUTIVE_GATE,
        "ExecutiveApprovalGate",
        "Executive Gate",
        "Human-in-the-loop checkpoint that captures or auto-approves the executive decision.",
        HostingMode.SYSTEM,
        "decision",
        9,
        2,
        instructions=_instruction(
            "Executive Approval Gate",
            "Use the scenario evaluation and optional deliberation recommendation; no tools are available.",
            '''{
  "approvedOptionId": string,
  "approver": string,
  "notes": string,
  "autoApproved": boolean,
  "recommendationFollowed": boolean,
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.STORE_OPERATIONS,
        "StoreOperationsAgent",
        "Store Operations",
        "Converts the approved option into store/DC execution tasks, purchase-limit rules, signage, and operating KPIs.",
        HostingMode.FOUNDRY,
        "execution",
        10,
        1,
        tools=["get_stakeholders", "get_playbooks", "get_stores_for_skus", "get_warehouses"],
        instructions=_instruction(
            "Store Operations Agent",
            "Before answering, call get_stakeholders with store-operations, get_playbooks, get_stores_for_skus, and get_warehouses.",
            '''{
  "approvedOptionId": string,
  "storeActions": [{"actionId": string, "title": string, "ownerFunction": string, "ownerName": string, "dueDate": string, "priority": "critical" | "high" | "medium", "status": "open", "dependsOn": [string]}],
  "warehouseActions": [{"actionId": string, "warehouseId": string, "title": string, "ownerName": string, "dueDate": string, "status": "open"}],
  "purchaseLimitPolicy": {"enabled": boolean, "limitText": string, "exceptions": [string]},
  "storeSignage": [string],
  "kpis": [{"name": string, "target": string, "frequency": string}],
  "risks": [{"risk": string, "severity": string, "mitigation": string, "owner": string}],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.CUSTOMER_COMMUNICATION,
        "CustomerCommunicationAgent",
        "Customer Communication",
        "Creates customer, colleague, franchise, and media communications for the approved response.",
        HostingMode.FOUNDRY,
        "execution",
        10,
        3,
        tools=["get_stakeholders", "get_playbooks", "search_knowledge"],
        instructions=_instruction(
            "Customer Communication Agent",
            "Before answering, call get_stakeholders with communications, get_playbooks with category communication, and search_knowledge for signage and consumer communication standards.",
            '''{
  "approvedOptionId": string,
  "communicationObjectives": [string],
  "customerMessage": string,
  "storeColleagueBrief": string,
  "franchiseOrB2BMessage": string,
  "mediaHoldingStatement": string,
  "channels": [{"channel": string, "audience": string, "timing": string, "owner": string}],
  "claimsToAvoid": [string],
  "approvalsRequired": [{"approval": string, "approverFunction": string, "byDate": string}],
  "narrative": string
}''',
        ),
    ),
    AgentSpec(
        NodeId.EXECUTIVE_BRIEFING,
        "ExecutiveBriefingAgent",
        "Executive Briefing",
        "Produces the final board-level shortage briefing, decision record, execution status, and residual risks.",
        HostingMode.FOUNDRY,
        "execution",
        11,
        2,
        instructions=_instruction(
            "Executive Briefing Agent",
            "Use the signal, synthesis, evaluation, decision, store operations plan, and communication plan supplied in the prompt; no tools are available.",
            '''{
  "headline": string,
  "situation": string,
  "businessExposureEur": number,
  "decision": {"optionId": string, "title": string, "approvedBy": string, "rationale": string},
  "optionsConsidered": [{"optionId": string, "title": string, "costEur": number, "timeToImplementDays": number, "riskLevel": string, "customerImpact": string, "expectedOutcome": string, "whyNotChosen": string}],
  "executionPlan": {"storeOperationsSummary": string, "customerCommunicationSummary": string, "first24Hours": [string]},
  "residualRisks": [string],
  "expectedBusinessOutcome": string,
  "narrative": string
}''',
        ),
    ),
]

AGENTS_BY_NODE: dict[str, AgentSpec] = {spec.node_id.value: spec for spec in AGENTS}

DEPENDENCIES: dict[str, list[str]] = {
    "situation_assessment": ["signal_normalizer"],
    "historical_knowledge": ["situation_assessment"],
    "demand_forecast": ["historical_knowledge"],
    "network_inventory": ["historical_knowledge"],
    "financial_impact": ["historical_knowledge"],
    "store_impact": ["historical_knowledge"],
    "impact_synthesis": ["demand_forecast", "network_inventory", "financial_impact", "store_impact"],
    "response_planner": ["impact_synthesis"],
    "sourcing_procurement": ["response_planner"],
    "allocation_fairness": ["response_planner"],
    "substitution_assortment": ["response_planner"],
    "pricing_compliance": ["response_planner"],
    "logistics_cold_chain": ["response_planner"],
    "scenario_evaluation": ["sourcing_procurement", "allocation_fairness", "substitution_assortment", "pricing_compliance", "logistics_cold_chain"],
    "deliberation": ["scenario_evaluation"],
    "executive_gate": ["deliberation"],
    "store_operations": ["executive_gate"],
    "customer_communication": ["executive_gate"],
    "executive_briefing": ["store_operations", "customer_communication"],
}

EDGES: list[tuple[str, str]] = [
    (upstream, node_id)
    for node_id, upstreams in DEPENDENCIES.items()
    for upstream in upstreams
]


def graph_definition() -> dict[str, list[dict[str, object]]]:
    """Node and edge description consumed by the frontend to render the DAG."""
    nodes = [
        {
            "id": spec.node_id.value,
            "label": spec.label,
            "description": spec.description,
            "hostingMode": spec.hosting_mode.value,
            "group": spec.group,
            "row": spec.row,
            "col": spec.col,
        }
        for spec in AGENTS
    ]
    edges = [{"from": upstream, "to": node_id} for upstream, node_id in EDGES]
    return {"nodes": nodes, "edges": edges}
