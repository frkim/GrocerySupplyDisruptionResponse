# Business scenario

## Context

Vivalis Retail Group is a fictional grocery retailer with 1,180 stores supplied by 8 regional distribution centres. The reference disruption is a national shell-egg shortage caused by a highly pathogenic avian influenza outbreak. Laying-hen farms have been culled or quarantined, packing-centre throughput is constrained, and several normal domestic supply lanes can no longer confirm orders.

The first signal, `INC-2026-0042`, reports `SKU-EGG-0001` as the lead product, a `38.0` percent supply shortfall, a `44.0` percent demand surge, a four-to-nine-day depletion window, all five operating regions affected, and the source `databricks-stub`.

## Root cause

The immediate root cause is loss of laying-hen capacity and associated movement restrictions after the outbreak. The commercial root cause is broader: shoppers react to media coverage by stockpiling; live promotions amplify demand; and egg-dependent own-brand bakery and ready-meal products consume the same constrained supply pool. This makes the disruption both a retail shelf-availability problem and an upstream manufacturing input problem.

## Timeline

| Time window | Operational reality | Required system response |
| --- | --- | --- |
| Detection to 6 hours | Supplier confirmations and POS velocity show cover collapsing. | Normalize the signal, identify affected SKUs, DCs, regions, and confidence. |
| 6 to 24 hours | Store clusters diverge by format and region; promotions remain live. | Run demand, inventory, financial, and store impact assessments concurrently. |
| 24 to 48 hours | Buyers and supply-chain teams need feasible response options. | Generate sourcing, allocation, substitution, pricing, and logistics validations. |
| 48 to 72 hours | Executive owners need one controlled action plan. | Score options, deliberate if the recommendation is close, obtain approval, and issue execution guidance. |

## Who is hurt

* Store operations teams face empty shelves, rationing questions, colleague escalation, and uneven truck arrivals.
* Merchandising and marketing teams must pause or amend live egg promotions while managing printed leaflet commitments and digital content.
* Supply chain teams must rebalance scarce cases across regional DCs without creating unfairness.
* Private-label bakery and ready-meal teams are exposed through products whose `inputProductIds` reference shell-egg SKUs and whose `eggContentUnitsPerCase` creates hidden demand.
* Finance teams face lost margin, cancellation costs, penalty exposure, and higher supplier prices.
* Quality, legal, and communications teams must ensure food-safety, animal-welfare, consumer-protection, and signage standards are met.

## Commercial and regulatory stakes

The retailer must keep traffic-driver egg SKUs available enough to preserve trust without encouraging panic buying. It must protect priority commitments, avoid misleading pricing or promotion claims, and ensure any substitution or reformulation respects labelling, allergen, and food-safety requirements. Import options may add lead time, cost, sustainability impact, and qualification risk. Purchase limits and fair-share allocation must be explainable across store formats and regions.

## Decisions in the first 72 hours

1. Which response option `A`, `B`, `C`, or `D` should be approved.
2. Whether to pause, amend, or continue live promotions in `promotions.json`.
3. How to allocate available and in-transit cases across warehouses and store clusters.
4. Which alternative suppliers or processors can be qualified quickly enough.
5. Which substitutes or reformulations can protect private-label bakery and ready-meal SKUs.
6. Whether customer-facing purchase limits, signage, and digital messages are required.
7. Which executive, legal, quality, supply-chain, merchandising, and communications owners must act immediately.

## Optimised outcomes

The system optimises for measurable outcomes: higher shelf availability, lower days-of-cover volatility, lower revenue and margin exposure, lower penalty exposure, fairer regional allocation, compliant pricing and communications, feasible chilled logistics, sustainable sourcing choices, and a documented executive decision record.

