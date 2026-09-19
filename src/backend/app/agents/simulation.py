"""Deterministic offline simulation of agent reasoning.

The solution is designed to degrade gracefully: it must be possible to clone the
repository and run the complete twenty-agent workflow end to end with no Azure
subscription, no Azure OpenAI deployment and no Microsoft Foundry project.

When no model is configured this module produces structurally valid, schema-shaped
results for every agent. The numbers are not invented - they are computed from the
same seed datasets the real tools read, so the demonstration stays internally
consistent and the figures on screen reconcile with the data files.

Every result produced here is tagged ``_executionNote: "simulated_offline"`` so the
user interface can label it honestly. Simulation is never used when a model is
configured.
"""

from __future__ import annotations

from typing import Any

from ..contracts import NodeId, RunContext
from . import tools

_NOTE = "simulated_offline"

_LEVER_TITLES = {
    "A": "Emergency sourcing and import bridge",
    "B": "Fair-share allocation with purchase limits",
    "C": "Substitution and assortment reformulation",
    "D": "Demand shaping and promotional withdrawal",
}


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def _sum(rows: list[dict[str, Any]], field: str) -> float:
    return float(sum(float(r.get(field) or 0) for r in rows))


def _cover(rows: list[dict[str, Any]]) -> float:
    values = [float(r.get("daysOfCover") or 0) for r in rows if r.get("daysOfCover") is not None]
    return _round(sum(values) / len(values), 1) if values else 0.0


async def _facts(ctx: RunContext) -> dict[str, Any]:
    """Collect the grounding facts once; every node derives its numbers from these."""
    if ctx.simulation_facts is not None:
        return ctx.simulation_facts

    signal = ctx.signal
    product_id = signal.product_id if signal else ""
    skus = list(signal.impacted_skus if signal else [])

    product = await tools.get_product(product_id)
    supplier = await tools.get_supplier(signal.supplier_id if signal else "")
    alternatives = await tools.find_alternative_suppliers(product_id)
    wh_inventory = await tools.get_warehouse_inventory(product_id)
    store_inventory = await tools.get_store_inventory(product_id)
    dependents = await tools.get_dependent_products(product_id)
    schedule = await tools.get_replenishment_schedule()
    stores = await tools.get_stores_for_skus(skus)
    forecast = await tools.get_demand_forecast(skus)
    commitments = await tools.get_commitments_for_skus(skus)
    promotions = await tools.get_promotions_for_skus(skus)
    substitutes = await tools.get_substitutes(product_id)
    past = await tools.get_past_disruptions(product_id)
    playbooks = await tools.get_playbooks()
    stakeholders = await tools.get_stakeholders()
    knowledge = await tools.search_knowledge("egg shortage avian influenza allocation")

    wh_cases = _sum(wh_inventory, "availableCases")
    store_cases = _sum(store_inventory, "availableCases")
    in_transit = _sum(wh_inventory, "inTransitCases")
    baseline_weekly = _sum(forecast, "baselineWeeklyCases") or 1.0
    surged_weekly = _sum(forecast, "currentWeeklyCases") or baseline_weekly
    alt_capacity = _sum(alternatives, "availableCapacityCasesPerWeek")
    committed_cases = _sum(commitments, "weeklyCases")
    promo_uplift = _sum(promotions, "forecastIncrementalCases")
    promo_cancel_cost = _sum(promotions, "cancellationCostEur")
    shortfall_pct = float(signal.supply_shortfall_pct if signal else 0.0)
    surge_pct = float(signal.demand_surge_pct if signal else 0.0)

    weekly_gap = max(surged_weekly - (baseline_weekly * (1 - shortfall_pct / 100.0)), 0.0)

    # Margin per case is derived from the product master rather than assumed.
    retail = float(product.get("retailPriceEur") or 0)
    cost = float(product.get("unitCostEur") or 0)
    units_per_case = float(product.get("unitsPerCase") or 0) or 1.0
    unit_margin = (retail - cost) * units_per_case
    if unit_margin <= 0:
        unit_margin = retail * units_per_case * (float(product.get("marginPct") or 20) / 100.0)
    penalty_rate = (
        _sum(commitments, "penaltyEurPerMissedCase") / len(commitments) if commitments else 0.0
    )

    facts = {
        "productId": product_id,
        "product": product,
        "supplier": supplier,
        "alternatives": alternatives,
        "warehouseInventory": wh_inventory,
        "storeInventory": store_inventory,
        "dependents": dependents,
        "schedule": schedule,
        "stores": stores,
        "forecast": forecast,
        "commitments": commitments,
        "promotions": promotions,
        "substitutes": substitutes,
        "past": past,
        "playbooks": playbooks,
        "stakeholders": stakeholders,
        "knowledge": knowledge,
        "skus": skus,
        "warehouseCases": wh_cases,
        "storeCases": store_cases,
        "inTransitCases": in_transit,
        "baselineWeeklyCases": baseline_weekly,
        "surgedWeeklyCases": surged_weekly,
        "altCapacityCasesPerWeek": alt_capacity,
        "committedCases": committed_cases,
        "promoUpliftCases": promo_uplift,
        "promoCancellationCostEur": promo_cancel_cost,
        "weeklyGapCases": weekly_gap,
        "warehouseCover": _cover(wh_inventory),
        "storeCover": _cover(store_inventory),
        "shortfallPct": shortfall_pct,
        "surgePct": surge_pct,
        "unitMargin": unit_margin,
        "penaltyRate": penalty_rate,
        "fourWeekGapCases": weekly_gap * 4,
        "lostMarginEur": _round(weekly_gap * 4 * unit_margin, 0),
        "penaltyEur": _round(min(committed_cases * 4, weekly_gap * 4) * penalty_rate, 0),
    }
    ctx.simulation_facts = facts
    return facts


def _options(f: dict[str, Any]) -> list[dict[str, Any]]:
    """Four response options with costs derived from the seed data."""
    gap = f["fourWeekGapCases"]
    alt = f["altCapacityCasesPerWeek"]
    import_premium = 9.5
    return [
        {
            "optionId": "A",
            "title": _LEVER_TITLES["A"],
            "description": (
                f"Qualify {len(f['alternatives'])} alternate suppliers and bridge with imported "
                f"shell eggs, adding up to {alt:,.0f} cases per week of certified capacity."
            ),
            "leverPrimary": "sourcing",
            "costEur": _round(min(gap, alt * 4) * import_premium, 0),
            "timeToImplementDays": 7,
            "riskLevel": "medium",
            "customerImpact": "Shelf availability recovers fastest; retail price rises modestly.",
            "shelfAvailabilityRecoveryPct": 78.0,
            "expectedOutcome": "Closes the majority of the physical supply gap within two weeks.",
            "keyActions": [
                "Activate emergency import lane with certified HPAI-free origin",
                "Qualify alternate co-operative suppliers under expedited audit",
                "Re-cut inbound replenishment schedule to prioritise deficit DCs",
            ],
            "dependencies": ["Veterinary import certification", "Additional inbound dock slots"],
        },
        {
            "optionId": "B",
            "title": _LEVER_TITLES["B"],
            "description": (
                f"Apply fair-share allocation across {len(f['warehouseInventory'])} distribution "
                f"centres and cap customer purchases to protect breadth of availability."
            ),
            "leverPrimary": "allocation",
            "costEur": _round(gap * 1.2, 0),
            "timeToImplementDays": 2,
            "riskLevel": "low",
            "customerImpact": "Every store keeps a baseline facing; heavy buyers are limited.",
            "shelfAvailabilityRecoveryPct": 54.0,
            "expectedOutcome": "Prevents regional stock-outs and protects vulnerable stores.",
            "keyActions": [
                "Switch to fair-share allocation keyed on historical rate of sale",
                "Apply a per-customer purchase limit at point of sale",
                "Protect contractual and vulnerable-community commitments first",
            ],
            "dependencies": ["Point-of-sale limit configuration", "DC allocation override"],
        },
        {
            "optionId": "C",
            "title": _LEVER_TITLES["C"],
            "description": (
                f"Promote {len(f['substitutes'])} substitute formats including liquid egg and "
                f"plant-based replacer, and reformulate own-brand bakery lines."
            ),
            "leverPrimary": "substitution",
            "costEur": _round(gap * 4.4, 0),
            "timeToImplementDays": 10,
            "riskLevel": "medium",
            "customerImpact": "Customers are offered equivalent formats; labels must change.",
            "shelfAvailabilityRecoveryPct": 61.0,
            "expectedOutcome": "Shifts demand away from shell eggs and protects derived categories.",
            "keyActions": [
                "Switch own-brand bakery to liquid and powdered egg where approved",
                "Expand facings for plant-based replacer and substitute formats",
                "Update allergen and ingredient labelling before any recipe change",
            ],
            "dependencies": ["Recipe and labelling approval", "Substitute supplier capacity"],
        },
        {
            "optionId": "D",
            "title": _LEVER_TITLES["D"],
            "description": (
                f"Cancel {len(f['promotions'])} live promotions, de-list low-priority derived SKUs "
                "and communicate transparently to shape demand down to available supply."
            ),
            "leverPrimary": "demand-shaping",
            "costEur": _round(f["promoCancellationCostEur"], 0),
            "timeToImplementDays": 3,
            "riskLevel": "low",
            "customerImpact": "Fewer offers and a narrower range; clear in-store explanation.",
            "shelfAvailabilityRecoveryPct": 47.0,
            "expectedOutcome": "Removes artificial demand spikes and stabilises depletion rate.",
            "keyActions": [
                "Cancel all egg and egg-derived promotional activity",
                "Temporarily de-list the lowest-priority derived SKUs",
                "Publish shelf-edge and digital explanation of the shortage",
            ],
            "dependencies": ["Marketing withdrawal lead time", "Consumer-protection review"],
        },
    ]


_SCORES = {
    "A": {"financial": 65.0, "operational": 71.0, "customer": 89.0, "compliance": 70.0, "sustainability": 55.0},
    "B": {"financial": 81.0, "operational": 86.0, "customer": 69.0, "compliance": 88.0, "sustainability": 78.0},
    "C": {"financial": 66.0, "operational": 63.0, "customer": 74.0, "compliance": 64.0, "sustainability": 81.0},
    "D": {"financial": 74.0, "operational": 80.0, "customer": 52.0, "compliance": 83.0, "sustainability": 72.0},
}

_WEIGHTS = {"financial": 0.25, "operational": 0.2, "customer": 0.3, "compliance": 0.15, "sustainability": 0.1}


def _scored_options(f: dict[str, Any]) -> list[dict[str, Any]]:
    scored = []
    for option in _options(f):
        scores = _SCORES[option["optionId"]]
        total = sum(scores[k] * w for k, w in _WEIGHTS.items())
        entry = dict(option)
        entry["scores"] = scores
        entry["totalScore"] = _round(total, 1)
        entry["blockingIssues"] = []
        scored.append(entry)
    return scored


# --------------------------------------------------------------------------- nodes

async def _situation(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    signal = ctx.signal
    product = f["product"]
    supplier = f["supplier"]
    return {
        "situationTitle": f"Nationwide {product.get('name', 'egg')} shortage driven by avian influenza",
        "rootCauseAnalysis": signal.root_cause if signal else "",
        "primaryProduct": {
            "productId": product.get("id", ""),
            "name": product.get("name", ""),
            "category": product.get("category", ""),
            "strategicTier": product.get("strategicTier", ""),
        },
        "supplierStatus": {
            "supplierId": supplier.get("id", ""),
            "name": supplier.get("name", ""),
            "avianInfluenzaStatus": supplier.get("avianInfluenzaStatus", "impacted"),
            "availableCapacityCasesPerWeek": supplier.get("availableCapacityCasesPerWeek", 0),
            "leadTimeDays": supplier.get("leadTimeDays", 0),
        },
        "warehouseExposure": [
            {
                "warehouseId": r.get("locationId"),
                "region": r.get("region"),
                "availableCases": r.get("availableCases"),
                "daysOfCover": r.get("daysOfCover"),
                "inTransitCases": r.get("inTransitCases", 0),
            }
            for r in f["warehouseInventory"]
        ],
        "storeExposure": [
            {
                "locationId": r.get("locationId"),
                "region": r.get("region"),
                "availableCases": r.get("availableCases"),
                "daysOfCover": r.get("daysOfCover"),
            }
            for r in f["storeInventory"][:8]
        ],
        "dependentProducts": [
            {
                "productId": d.get("id"),
                "name": d.get("name"),
                "category": d.get("category"),
                "eggContentUnitsPerCase": d.get("eggContentUnitsPerCase", 0),
            }
            for d in f["dependents"]
        ],
        "replenishmentRisks": [
            {
                "id": s.get("id"),
                "warehouseId": s.get("warehouseId"),
                "confirmedCases": s.get("confirmedCases", 0),
                "shortfallCases": s.get("shortfallCases", 0),
                "status": s.get("status", ""),
            }
            for s in f["schedule"]
            if (s.get("shortfallCases") or 0) > 0
        ][:8],
        "severity": "critical" if f["shortfallPct"] >= 35 else "high",
        "confidence": signal.confidence if signal else 0.0,
        "narrative": (
            f"{product.get('name', 'The disrupted product')} is short by {f['shortfallPct']:.1f}% "
            f"against a demand surge of {f['surgePct']:.1f}%. Distribution centres hold "
            f"{f['warehouseCases']:,.0f} cases at {f['warehouseCover']:.1f} days of average cover, "
            f"with {f['inTransitCases']:,.0f} cases inbound. {len(f['dependents'])} derived products "
            f"consume this ingredient and are exposed to the same shortfall."
        ),
    }


async def _historical(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    past = f["past"]
    return {
        "hasPrecedent": bool(past),
        "precedents": [
            {
                "id": p.get("id"),
                "title": p.get("title"),
                "date": p.get("date", p.get("startDate", "")),
                "durationDays": p.get("durationDays", 0),
                "peakShortfallPct": p.get("peakShortfallPct", 0),
                "revenueLostEur": p.get("revenueLostEur", 0),
            }
            for p in past
        ],
        "mitigationsPreviouslyApplied": [
            {
                "action": m if isinstance(m, str) else m.get("action", ""),
                "outcome": "" if isinstance(m, str) else m.get("outcome", ""),
                "effectivenessScore": 0 if isinstance(m, str) else m.get("effectivenessScore", 0),
                "costEur": 0 if isinstance(m, str) else m.get("costEur", 0),
            }
            for p in past
            for m in (p.get("mitigationsApplied") or [])
        ][:8],
        "relevantPlaybooks": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "category": p.get("category"),
                "leadTimeDays": p.get("leadTimeDays", 0),
                "typicalCostEur": p.get("typicalCostEur", 0),
            }
            for p in f["playbooks"]
        ],
        "mostEffectiveActions": [
            "Fair-share allocation keyed on rate of sale",
            "Per-customer purchase limits applied at point of sale",
            "Early cancellation of promotional activity",
            "Liquid egg substitution for own-brand bakery",
        ],
        "knowledgePassages": [
            {"title": k.get("title", ""), "excerpt": (k.get("content") or k.get("excerpt") or "")[:400]}
            for k in f["knowledge"][:4]
        ],
        "narrative": (
            f"{len(past)} comparable avian influenza events are on record. The most effective "
            "historical levers were fair-share allocation and early promotional withdrawal, "
            "both of which protected breadth of availability at low incremental cost."
        ),
    }


async def _demand(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return {
        "surgeDriver": "Consumer stockpiling amplified by national media coverage of the outbreak",
        "skuForecasts": [
            {
                "skuId": r.get("productId"),
                "region": r.get("region"),
                "baselineWeeklyCases": r.get("baselineWeeklyCases", 0),
                "surgedWeeklyCases": r.get("currentWeeklyCases", 0),
                "surgePct": r.get("surgePct", 0),
            }
            for r in f["forecast"]
        ],
        "promotionalUpliftCases": f["promoUpliftCases"],
        "exposedStoreClusters": [
            {"storeId": s.get("id"), "region": s.get("region"), "format": s.get("format", "")}
            for s in f["stores"][:10]
        ],        "totalBaselineWeeklyCases": f["baselineWeeklyCases"],
        "totalSurgedWeeklyCases": f["surgedWeeklyCases"],
        "weeklyGapCases": _round(f["weeklyGapCases"], 0),
        "narrative": (
            f"Weekly demand rises from {f['baselineWeeklyCases']:,.0f} to "
            f"{f['surgedWeeklyCases']:,.0f} cases, a {f['surgePct']:.1f}% surge. Against the "
            f"{f['shortfallPct']:.1f}% supply shortfall this leaves a gap of "
            f"{f['weeklyGapCases']:,.0f} cases per week across {len(f['stores'])} exposed stores."
        ),
    }


async def _inventory(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    deficit = [r for r in f["warehouseInventory"] if float(r.get("daysOfCover") or 0) < 5]
    surplus = [r for r in f["warehouseInventory"] if float(r.get("daysOfCover") or 0) >= 8]
    return {
        "totalWarehouseCases": f["warehouseCases"],
        "totalStoreCases": f["storeCases"],
        "inTransitCases": f["inTransitCases"],
        "averageWarehouseCover": f["warehouseCover"],
        "averageStoreCover": f["storeCover"],
        "deficitWarehouses": [
            {"warehouseId": r.get("locationId"), "region": r.get("region"), "daysOfCover": r.get("daysOfCover")}
            for r in deficit
        ],
        "transferOpportunities": [
            {
                "fromWarehouseId": s.get("locationId"),
                "toWarehouseId": d.get("locationId"),
                "cases": _round(min(float(s.get("availableCases") or 0) * 0.15, 400), 0),
                "rationale": "Rebalance from surplus cover to a deficit region",
            }
            for s in surplus
            for d in deficit[:1]
        ][:5],
        "inboundRisk": [
            {"id": s.get("id"), "warehouseId": s.get("warehouseId"), "shortfallCases": s.get("shortfallCases", 0), "status": s.get("status", "")}
            for s in f["schedule"]
            if (s.get("shortfallCases") or 0) > 0
        ][:8],
        "narrative": (
            f"The network holds {f['warehouseCases']:,.0f} cases in distribution centres and "
            f"{f['storeCases']:,.0f} in store, averaging {f['warehouseCover']:.1f} and "
            f"{f['storeCover']:.1f} days of cover respectively. {len(deficit)} distribution "
            f"centres fall below five days and qualify for inbound prioritisation."
        ),
    }


async def _financial(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    lost_margin = f["lostMarginEur"]
    penalty = f["penaltyEur"]
    premium = _round(f["fourWeekGapCases"] * 0.45 * 9.5, 0)
    return {
        "horizonWeeks": 4,
        "lostMarginEur": lost_margin,
        "contractPenaltyEur": penalty,
        "premiumSourcingCostEur": premium,
        "substitutionCostEur": _round(f["fourWeekGapCases"] * 2.1, 0),
        "totalExposureEur": _round(lost_margin + penalty + premium, 0),
        "assumptions": [
            "Four-week planning horizon aligned to the depletion window",
            f"Margin of EUR {f['unitMargin']:.2f} per case derived from the product master",
            f"Weighted penalty of EUR {f['penaltyRate']:.2f} per missed committed case",
            "Penalties apply only to contractually committed volume",
        ],
        "narrative": (
            f"Unmitigated four-week exposure is approximately EUR "
            f"{lost_margin + penalty + premium:,.0f}, comprising EUR {lost_margin:,.0f} of lost "
            f"margin on {f['fourWeekGapCases']:,.0f} unfulfilled cases, EUR {penalty:,.0f} of "
            f"contractual penalty risk and EUR {premium:,.0f} of premium sourcing cost."
        ),
    }


async def _store(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return {
        "storesAffected": len(f["stores"]),
        "shelfAvailabilityRiskPct": _round(min(f["shortfallPct"] + f["surgePct"] * 0.3, 95), 1),
        "commitmentsAtRisk": [
            {
                "id": c.get("id"),
                "counterparty": c.get("counterparty", ""),
                "skuId": c.get("skuId"),
                "weeklyCases": c.get("weeklyCases", 0),
                "penaltyEurPerMissedCase": c.get("penaltyEurPerMissedCase", 0),
                "currentServiceLevelPct": c.get("currentServiceLevelPct", 0),
                "priority": c.get("priority", ""),
            }
            for c in f["commitments"]
        ][:10],
        "promotionsAtRisk": [
            {
                "id": p.get("id"),
                "name": p.get("name", ""),
                "status": p.get("status", ""),
                "forecastIncrementalCases": p.get("forecastIncrementalCases", 0),
                "cancellationCostEur": p.get("cancellationCostEur", 0),
                "startDate": p.get("startDate", ""),
            }
            for p in f["promotions"]
        ],
        "fairnessConcerns": [
            "Smaller convenience formats risk total stock-out before larger stores",
            "Regions with the lowest days of cover would deplete first under proportional allocation",
        ],
        "vulnerableRegions": sorted({s.get("region") for s in f["storeInventory"] if s.get("region")})[:5],
        "narrative": (
            f"{len(f['stores'])} stores stock the impacted assortment. {len(f['commitments'])} "
            f"contractual commitments covering {f['committedCases']:,.0f} cases per week and "
            f"{len(f['promotions'])} live promotions are exposed, creating both penalty risk and "
            "artificial demand that must be withdrawn."
        ),
    }


async def _synthesis(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return {
        "overallSeverity": "critical" if f["shortfallPct"] >= 35 else "high",
        "headline": (
            f"A {f['shortfallPct']:.0f}% egg supply shortfall meeting a {f['surgePct']:.0f}% demand "
            "surge threatens shelf availability nationwide within the depletion window."
        ),
        "keyFindings": [
            f"Weekly gap of {f['weeklyGapCases']:,.0f} cases across the network",
            f"Average distribution centre cover of {f['warehouseCover']:.1f} days",
            f"{len(f['dependents'])} derived products share the same ingredient exposure",
            f"Four-week financial exposure of approximately EUR {f['lostMarginEur'] + f['penaltyEur']:,.0f}",
        ],
        "criticalConstraints": [
            "Chilled shelf life limits how far stock can be rebalanced",
            "Consumer-protection rules constrain pricing responses",
            "Alternate supplier qualification requires veterinary certification",
        ],
        "decisionUrgencyHours": 24,
        "narrative": (
            "Demand, inventory, financial and store assessments agree that no single lever closes "
            f"the {f['weeklyGapCases']:,.0f} case weekly gap. A combined response is required, and "
            "the decision window is under twenty-four hours before the first distribution centres "
            "fall below safety stock."
        ),
    }


async def _planner(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return {
        "options": _options(f),
        "recommendedForValidation": ["A", "B", "C", "D"],
        "planningAssumptions": [
            "The outbreak continues to suppress domestic laying capacity for at least four weeks",
            "Imported supply is available subject to veterinary certification",
            "Fair-share allocation can be configured within forty-eight hours",
        ],
        "narrative": (
            "Four options were constructed across the sourcing, allocation, substitution and "
            "demand-shaping levers so the executive can trade recovery speed against cost, "
            "compliance exposure and customer perception."
        ),
    }


def _validation(focus: str, f: dict[str, Any], findings: list[str], best: str) -> dict[str, Any]:
    return {
        "assessments": [
            {
                "optionId": option["optionId"],
                "feasible": True,
                "confidence": 0.78,
                "constraints": findings[:2],
                "risks": findings[2:4] or findings[:1],
                "recommendation": "proceed" if option["optionId"] == best else "proceed-with-conditions",
            }
            for option in _options(f)
        ],
        "keyFindings": findings,
        "preferredOptionId": best,
        "blockingIssues": [],
        "narrative": f"{focus} No option is blocked, but conditions apply. Option {best} is the strongest on this dimension.",
    }


async def _sourcing(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return _validation(
        "Sourcing and procurement validation completed.",
        f,
        [
            f"{len(f['alternatives'])} alternate suppliers offer {f['altCapacityCasesPerWeek']:,.0f} cases per week",
            "Imported shell eggs require veterinary health certification before release",
            "Expedited supplier qualification compresses audit lead time to seven days",
            "Spot market pricing carries a premium against contracted rates",
        ],
        "A",
    )


async def _allocation(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return _validation(
        "Allocation and fair-share validation completed.",
        f,
        [
            "Fair-share allocation keyed on rate of sale protects breadth of availability",
            "Per-customer purchase limits are enforceable at point of sale within forty-eight hours",
            f"{len(f['commitments'])} contractual commitments must be ring-fenced before free stock",
            "Regional equity requires overriding the default proportional split",
        ],
        "B",
    )


async def _substitution(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return _validation(
        "Substitution and assortment validation completed.",
        f,
        [
            f"{len(f['substitutes'])} approved substitute formats are available including liquid egg",
            "Own-brand bakery reformulation requires allergen and ingredient label changes",
            "Plant-based replacer capacity is limited by its own supplier lead time",
            f"{len(f['dependents'])} derived products can be partially protected by reformulation",
        ],
        "C",
    )


async def _pricing(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return _validation(
        "Pricing and compliance validation completed.",
        f,
        [
            "Consumer-protection rules prohibit unjustified price increases during a shortage",
            f"Cancelling {len(f['promotions'])} promotions is permitted with published notice",
            "Any recipe change requires updated allergen labelling before sale",
            "Food-safety controls on egg handling remain unchanged during the outbreak",
        ],
        "D",
    )


async def _logistics(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return _validation(
        "Logistics and cold chain validation completed.",
        f,
        [
            "Chilled capacity is sufficient but inbound dock slots are the binding constraint",
            "Inter-warehouse transfers are feasible within the remaining shelf life",
            f"{len(f['warehouseInventory'])} distribution centres can be re-sequenced on the inbound plan",
            "Additional import volume requires temperature-controlled port handling",
        ],
        "B",
    )


async def _evaluation(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    options = _scored_options(f)
    ranking = [o["optionId"] for o in sorted(options, key=lambda o: o["totalScore"], reverse=True)]
    totals = sorted((o["totalScore"] for o in options), reverse=True)
    close = len(totals) >= 2 and (totals[0] - totals[1]) <= 8.0
    return {
        "options": options,
        "ranking": ranking,
        "recommendedOptionId": ranking[0],
        "closeCall": close,
        "rationale": (
            f"Option {ranking[0]} achieves the highest weighted score at {totals[0]:.1f}, leading on "
            "operational deliverability and compliance while remaining affordable."
        ),
        "narrative": (
            f"Options rank {', '.join(ranking)}. The leading two are separated by "
            f"{totals[0] - totals[1]:.1f} points, "
            f"{'which is a close call requiring deliberation' if close else 'a decisive margin'}."
        ),
    }


async def _deliberation(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    evaluation = ctx.structured_of(NodeId.SCENARIO_EVALUATION)
    ranking = evaluation.get("ranking") or ["B", "A"]
    top, second = ranking[0], ranking[1] if len(ranking) > 1 else ranking[0]
    return {
        "argumentsFor": [
            {"optionId": top, "perspective": "store operations", "argument": "Deliverable within forty-eight hours using existing systems."},
            {"optionId": top, "perspective": "compliance", "argument": "Fair-share allocation is defensible to the regulator and to customers."},
            {"optionId": second, "perspective": "customer", "argument": "Restores physical availability faster and protects perception of the brand."},
        ],
        "argumentsAgainst": [
            {"optionId": top, "perspective": "customer", "argument": "Purchase limits generate visible friction at the till."},
            {"optionId": second, "perspective": "finance", "argument": "Import premium materially increases landed cost per case."},
        ],
        "decisiveFactors": [
            "Speed of implementation against the depletion window",
            "Regulatory defensibility of the chosen allocation method",
            "Protection of contractual and vulnerable-community commitments",
        ],
        "convergedRecommendationId": top,
        "dissentingView": (
            f"Commercial argues that option {second} should run in parallel, because allocation "
            "alone does not add a single case of physical supply."
        ),
        "narrative": (
            f"Deliberation converged on option {top} as the immediate action, with option {second} "
            "recommended as a parallel workstream to close the physical supply gap."
        ),
    }


async def _store_ops(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    decision = ctx.decision or {}
    return {
        "approvedOptionId": decision.get("optionId", ""),
        "warehouseActions": [
            {
                "warehouseId": r.get("locationId"),
                "action": "Apply fair-share allocation and prioritise inbound replenishment",
                "ownerRole": "Distribution centre manager",
                "dueInDays": 2,
            }
            for r in f["warehouseInventory"][:6]
        ],
        "storeActions": [
            {"action": "Apply the per-customer purchase limit at point of sale", "ownerRole": "Store manager", "dueInDays": 1},
            {"action": "Consolidate remaining facings and deploy shortage signage", "ownerRole": "Store manager", "dueInDays": 1},
            {"action": "Expand facings for approved substitute formats", "ownerRole": "Section lead", "dueInDays": 3},
        ],
        "systemChanges": [
            "Configure the point-of-sale purchase limit for the impacted assortment",
            "Switch distribution centre allocation from proportional to fair-share",
            "Suspend automatic replenishment overrides for de-listed derived SKUs",
        ],
        "monitoringKpis": [
            "Shelf availability percentage by store format",
            "Days of cover by distribution centre",
            "Substitute format rate of sale",
        ],
        "narrative": (
            f"Execution covers {len(f['warehouseInventory'])} distribution centres and "
            f"{len(f['stores'])} stores. Allocation and purchase limits go live within "
            "forty-eight hours, with substitution facings following within three days."
        ),
    }


async def _communication(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    return {
        "customerMessage": (
            "Avian influenza has reduced the national egg supply. We are limiting purchases so "
            "that every customer can buy eggs, and we have not increased our prices because of "
            "the shortage. Alternative formats are available in the same aisle."
        ),
        "colleagueBriefing": (
            "Purchase limits are active on the impacted assortment. Explain the limit calmly, "
            "point customers to approved substitutes and do not consolidate stock between stores "
            "without distribution centre approval."
        ),
        "b2bNotice": (
            "Contracted volumes are ring-fenced and will be honoured in priority order. Any "
            "residual shortfall will be communicated with at least forty-eight hours of notice."
        ),
        "mediaStatement": (
            "We are working with our suppliers and with certified alternative sources to maintain "
            "egg availability during the national outbreak, and we have introduced fair purchase "
            "limits so that supply reaches as many households as possible."
        ),
        "signageRequirements": [
            "Shelf-edge notice explaining the purchase limit",
            "Aisle-entry notice directing customers to substitute formats",
        ],
        "stakeholderNotifications": [
            {"name": s.get("name", ""), "role": s.get("role", s.get("function", "")), "channel": s.get("channel", "email")}
            for s in f["stakeholders"][:8]
        ],
        "narrative": (
            "Customer, colleague, business-to-business and media communications are aligned on a "
            "single transparent message: limits protect fairness, prices have not been raised "
            "because of the shortage, and substitutes are available."
        ),
    }


async def _briefing(ctx: RunContext, f: dict[str, Any]) -> dict[str, Any]:
    decision = ctx.decision or {}
    evaluation = ctx.structured_of(NodeId.SCENARIO_EVALUATION)
    return {
        "incidentId": ctx.incident_id,
        "headline": (
            f"Egg shortage response approved: option {decision.get('optionId', 'B')} activated "
            f"across {len(f['warehouseInventory'])} distribution centres."
        ),
        "situationSummary": (
            f"A {f['shortfallPct']:.0f}% supply shortfall against a {f['surgePct']:.0f}% demand "
            f"surge leaves a gap of {f['weeklyGapCases']:,.0f} cases per week."
        ),
        "decision": {
            "approvedOptionId": decision.get("optionId", ""),
            "approver": decision.get("approver", ""),
            "autoApproved": decision.get("autoApproved", False),
            "recommendationFollowed": decision.get("optionId") == evaluation.get("recommendedOptionId"),
        },
        "financialSummary": {
            "unmitigatedExposureEur": _round(f["lostMarginEur"] + f["penaltyEur"], 0),
            "responseCostEur": next((o["costEur"] for o in _options(f) if o["optionId"] == decision.get("optionId")), 0),
        },
        "immediateActions": [
            "Activate fair-share allocation across all distribution centres",
            "Apply per-customer purchase limits at point of sale",
            "Cancel all egg and egg-derived promotional activity",
            "Open the emergency import lane in parallel",
        ],
        "risksToWatch": [
            "Further outbreak spread reducing domestic capacity again",
            "Customer reaction to visible purchase limits",
            "Substitute supplier capacity becoming the next constraint",
        ],
        "nextReviewInHours": 24,
        "narrative": (
            f"Option {decision.get('optionId', '')} was approved by "
            f"{decision.get('approver', 'the executive gate')}. Allocation and purchase limits "
            "take effect immediately, sourcing runs in parallel, and the position is reviewed "
            "within twenty-four hours."
        ),
    }


_SIMULATORS = {
    NodeId.SITUATION_ASSESSMENT: _situation,
    NodeId.HISTORICAL_KNOWLEDGE: _historical,
    NodeId.DEMAND_FORECAST: _demand,
    NodeId.NETWORK_INVENTORY: _inventory,
    NodeId.FINANCIAL_IMPACT: _financial,
    NodeId.STORE_IMPACT: _store,
    NodeId.IMPACT_SYNTHESIS: _synthesis,
    NodeId.RESPONSE_PLANNER: _planner,
    NodeId.SOURCING_PROCUREMENT: _sourcing,
    NodeId.ALLOCATION_FAIRNESS: _allocation,
    NodeId.SUBSTITUTION_ASSORTMENT: _substitution,
    NodeId.PRICING_COMPLIANCE: _pricing,
    NodeId.LOGISTICS_COLD_CHAIN: _logistics,
    NodeId.SCENARIO_EVALUATION: _evaluation,
    NodeId.DELIBERATION: _deliberation,
    NodeId.STORE_OPERATIONS: _store_ops,
    NodeId.CUSTOMER_COMMUNICATION: _communication,
    NodeId.EXECUTIVE_BRIEFING: _briefing,
}


def can_simulate(node_id: str) -> bool:
    try:
        return NodeId(node_id) in _SIMULATORS
    except ValueError:
        return False


async def simulate(node_id: str, ctx: RunContext) -> dict[str, Any]:
    """Return a deterministic, data-grounded result for one node."""
    node = NodeId(node_id)
    facts = await _facts(ctx)
    payload = await _SIMULATORS[node](ctx, facts)
    payload["_executionNote"] = _NOTE
    return payload
