"""Function tools exposed to grocery disruption agents.

Each tool has an OpenAI schema plus an async handler over the grocery domain data.
Descriptions are intentionally specific so model-hosted agents choose the right tool.
"""

from __future__ import annotations

from typing import Any

from ..data import get_repository
from ..knowledge import get_knowledge


async def get_product(product_id: str) -> dict[str, Any]:
    repo = await get_repository()
    return await repo.by_id("products", product_id) or {"error": "not found"}


async def get_supplier(supplier_id: str) -> dict[str, Any]:
    repo = await get_repository()
    return await repo.by_id("suppliers", supplier_id) or {"error": "not found"}


async def find_alternative_suppliers(product_id: str) -> list[dict[str, Any]]:
    repo = await get_repository()
    product = await repo.by_id("products", product_id)
    if not product:
        return []
    return await repo.by_ids("suppliers", list(product.get("alternateSupplierIds") or []))


async def get_warehouse_inventory(product_id: str) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("inventory")
    return [r for r in rows if r.get("productId") == product_id and r.get("locationType") == "warehouse"]


async def get_store_inventory(product_id: str, region: str | None = None) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("inventory")
    result = [r for r in rows if r.get("productId") == product_id and r.get("locationType") == "store"]
    if region:
        result = [r for r in result if r.get("region") == region]
    return result


async def get_dependent_products(product_id: str) -> list[dict[str, Any]]:
    repo = await get_repository()
    products = await repo.all("products")
    return [p for p in products if product_id in (p.get("inputProductIds") or [])]


async def get_warehouses(warehouse_ids: list[str] | None = None) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("warehouses")
    if warehouse_ids:
        wanted = set(warehouse_ids)
        rows = [r for r in rows if r.get("id") in wanted]
    return rows


async def get_replenishment_schedule(warehouse_id: str | None = None) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("replenishmentSchedule")
    if warehouse_id:
        rows = [r for r in rows if r.get("warehouseId") == warehouse_id]
    return rows[:40]


async def get_stores_for_skus(sku_ids: list[str]) -> list[dict[str, Any]]:
    repo = await get_repository()
    wanted = set(sku_ids)
    rows = await repo.all("stores")
    return [r for r in rows if wanted & set(r.get("skusStocked") or [])]


async def get_demand_forecast(sku_ids: list[str]) -> list[dict[str, Any]]:
    repo = await get_repository()
    wanted = set(sku_ids)
    return [r for r in await repo.all("demandForecast") if r.get("productId") in wanted]


async def get_commitments_for_skus(sku_ids: list[str]) -> list[dict[str, Any]]:
    repo = await get_repository()
    wanted = set(sku_ids)
    return [c for c in await repo.all("commitments") if c.get("skuId") in wanted]


async def get_promotions_for_skus(sku_ids: list[str]) -> list[dict[str, Any]]:
    repo = await get_repository()
    wanted = set(sku_ids)
    promos = await repo.all("promotions")
    return [p for p in promos if wanted & set(p.get("skuIds") or [])]


async def get_substitutes(product_id: str) -> list[dict[str, Any]]:
    repo = await get_repository()
    return [s for s in await repo.all("substitutes") if s.get("productId") == product_id]


async def get_past_disruptions(product_id: str | None = None) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("pastDisruptions")
    if product_id:
        matching = [r for r in rows if r.get("productId") == product_id]
        if matching:
            return matching
    return rows


async def get_playbooks(category: str | None = None) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("playbooks")
    if category:
        matching = [r for r in rows if r.get("category") == category]
        if matching:
            return matching
    return rows


async def get_stakeholders(function: str | None = None) -> list[dict[str, Any]]:
    repo = await get_repository()
    rows = await repo.all("stakeholders")
    if function:
        matching = [r for r in rows if r.get("function") == function]
        if matching:
            return matching
    return rows


async def search_knowledge(query: str) -> list[dict[str, Any]]:
    service = await get_knowledge()
    return await service.search(query, top=4)


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_STR = {"type": "string"}
_NULL_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_STR_ARRAY = {"type": "array", "items": {"type": "string"}}
_NULL_STR_ARRAY = {"anyOf": [_STR_ARRAY, {"type": "null"}]}

TOOL_REGISTRY: dict[str, tuple[dict[str, Any], Any]] = {
    "get_product": (
        _schema("get_product", "Look up one grocery SKU by product_id, including egg category, supplier links, weekly sales, unit economics, regions sold, and dependent input products.", {"product_id": _STR}, ["product_id"]),
        get_product,
    ),
    "get_supplier": (
        _schema("get_supplier", "Look up one egg supplier, packing centre, importer, or processor by supplier_id, including avian influenza status, capacity, lead time, price, reliability, certifications, and sustainability data.", {"supplier_id": _STR}, ["supplier_id"]),
        get_supplier,
    ),
    "find_alternative_suppliers": (
        _schema("find_alternative_suppliers", "For a disrupted grocery product_id, return supplier records listed in the product's alternateSupplierIds for emergency import, alternate co-op, processor, or packing-centre sourcing analysis.", {"product_id": _STR}, ["product_id"]),
        find_alternative_suppliers,
    ),
    "get_warehouse_inventory": (
        _schema("get_warehouse_inventory", "Return warehouse/DC inventory rows for a product_id, with on-hand, committed, available, in-transit cases, days of cover, safety stock, expiry risk, and region.", {"product_id": _STR}, ["product_id"]),
        get_warehouse_inventory,
    ),
    "get_store_inventory": (
        _schema("get_store_inventory", "Return store-cluster inventory rows for a product_id, optionally filtered by region, to assess shelf depletion and regional availability gaps.", {"product_id": _STR, "region": _NULL_STR}, ["product_id"]),
        get_store_inventory,
    ),
    "get_dependent_products": (
        _schema("get_dependent_products", "Find own-brand bakery, ready-meal, chilled, or ambient products whose inputProductIds contain the disrupted egg product_id.", {"product_id": _STR}, ["product_id"]),
        get_dependent_products,
    ),
    "get_warehouses": (
        _schema("get_warehouses", "Return regional distribution centre records, optionally limited to warehouse_ids, including capacity, utilization, stores served, cross-dock capability, and transfer lead times.", {"warehouse_ids": _NULL_STR_ARRAY}, []),
        get_warehouses,
    ),
    "get_replenishment_schedule": (
        _schema("get_replenishment_schedule", "Return scheduled inbound egg deliveries, optionally for one warehouse_id, capped at 40 rows with ordered, confirmed, shortfall cases and status.", {"warehouse_id": _NULL_STR}, []),
        get_replenishment_schedule,
    ),
    "get_stores_for_skus": (
        _schema("get_stores_for_skus", "Return store-cluster records that stock any sku_ids, including format, region, footfall, days of cover, shelf availability, and served warehouse.", {"sku_ids": _STR_ARRAY}, ["sku_ids"]),
        get_stores_for_skus,
    ),
    "get_demand_forecast": (
        _schema("get_demand_forecast", "Return baseline versus surge demand forecasts for sku_ids by region, including current surge percentage, four-week forecast, confidence, drivers, and price elasticity.", {"sku_ids": _STR_ARRAY}, ["sku_ids"]),
        get_demand_forecast,
    ),
    "get_commitments_for_skus": (
        _schema("get_commitments_for_skus", "Return franchise, wholesale, promotional, and private-label supply commitments for sku_ids, including weekly cases, service levels, penalties, and priority.", {"sku_ids": _STR_ARRAY}, ["sku_ids"]),
        get_commitments_for_skus,
    ),
    "get_promotions_for_skus": (
        _schema("get_promotions_for_skus", "Return live or planned grocery promotions for sku_ids, including uplift, incremental cases, cancellation cost, leaflet commitment, dates, and regions.", {"sku_ids": _STR_ARRAY}, ["sku_ids"]),
        get_promotions_for_skus,
    ),
    "get_substitutes": (
        _schema("get_substitutes", "Return substitute products for product_id with conversion ratio, availability, price delta, customer acceptance, labelling, allergen, lead time, and constraints.", {"product_id": _STR}, ["product_id"]),
        get_substitutes,
    ),
    "get_past_disruptions": (
        _schema("get_past_disruptions", "Return prior disruption records, optionally for product_id, including HPAI egg-shortage history, mitigations, costs, duration, peak shortfall, and lessons learned.", {"product_id": _NULL_STR}, []),
        get_past_disruptions,
    ),
    "get_playbooks": (
        _schema("get_playbooks", "Return grocery crisis response playbooks, optionally by category such as sourcing, allocation, substitution, pricing, communication, logistics, or promotion.", {"category": _NULL_STR}, []),
        get_playbooks,
    ),
    "get_stakeholders": (
        _schema("get_stakeholders", "Return stakeholder directory entries, optionally by function, with role, decision authority, escalation level, email, and covered regions.", {"function": _NULL_STR}, []),
        get_stakeholders,
    ),
    "search_knowledge": (
        _schema("search_knowledge", "Search the grocery disruption knowledge corpus for grounded passages from HPAI postmortems, allocation policy, egg substitution, pricing, regulation, signage, and sourcing standards.", {"query": _STR}, ["query"]),
        search_knowledge,
    ),
}


def schemas_for(names: list[str]) -> list[dict[str, Any]]:
    return [TOOL_REGISTRY[n][0] for n in names if n in TOOL_REGISTRY]


def handlers_for(names: list[str]) -> dict[str, Any]:
    return {n: TOOL_REGISTRY[n][1] for n in names if n in TOOL_REGISTRY}
