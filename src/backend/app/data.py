"""Cosmos DB access with an in-memory fallback.

If Cosmos is unreachable the repository serves the bundled seed JSON so the
Grocery Supply Disruption Response demo still runs end to end.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from azure.identity.aio import DefaultAzureCredential

from .config import get_settings
from .paths import data_dir

logger = logging.getLogger(__name__)

_CONTAINER_FILES = {
    "products": "products.json",
    "suppliers": "suppliers.json",
    "warehouses": "warehouses.json",
    "stores": "stores.json",
    "inventory": "inventory.json",
    "demandForecast": "demand-forecast.json",
    "substitutes": "substitutes.json",
    "commitments": "commitments.json",
    "promotions": "promotions.json",
    "replenishmentSchedule": "replenishment-schedule.json",
    "pastDisruptions": "past-disruptions.json",
    "playbooks": "playbooks.json",
    "stakeholders": "stakeholders.json",
    "signals": "signals.json",
}


class GroceryRepository:
    """Reads grocery disruption reference data. Prefers Cosmos, falls back to bundled JSON."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None
        self._credential: DefaultAzureCredential | None = None
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self.source = "unknown"

    async def initialize(self) -> None:
        if not self._settings.has_cosmos:
            self.source = "local-seed"
            logger.warning("COSMOS_ENDPOINT not set; using bundled seed data.")
            return
        try:
            from azure.cosmos.aio import CosmosClient

            self._credential = DefaultAzureCredential()
            self._client = CosmosClient(self._settings.cosmos_endpoint, credential=self._credential)
            database = self._client.get_database_client(self._settings.cosmos_database)
            container = database.get_container_client("products")
            probe = [item async for item in container.query_items("SELECT TOP 1 c.id FROM c")]
            self.source = "cosmos"
            logger.info("Cosmos DB reachable (probe returned %d rows).", len(probe))
        except Exception as exc:
            self.source = "local-seed"
            logger.warning("Cosmos unavailable (%s); using bundled seed data.", exc)
            await self._close_client()

    async def _close_client(self) -> None:
        try:
            if self._client is not None:
                await self._client.close()
        except Exception:
            pass
        self._client = None
        try:
            if self._credential is not None:
                await self._credential.close()
        except Exception:
            pass
        self._credential = None

    async def close(self) -> None:
        await self._close_client()

    def _load_local(self, container_name: str) -> list[dict[str, Any]]:
        filename = _CONTAINER_FILES.get(container_name)
        if not filename:
            return []
        path = data_dir() / filename
        if not path.exists():
            logger.warning("Seed file missing: %s", path)
            return []
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    async def all(self, container_name: str) -> list[dict[str, Any]]:
        if container_name in self._cache:
            return self._cache[container_name]

        items: list[dict[str, Any]] = []
        if self._client is not None:
            try:
                database = self._client.get_database_client(self._settings.cosmos_database)
                container = database.get_container_client(container_name)
                items = [item async for item in container.query_items("SELECT * FROM c")]
            except Exception as exc:
                logger.warning("Cosmos read failed for %s (%s); falling back.", container_name, exc)
                items = []

        if not items:
            items = self._load_local(container_name)

        self._cache[container_name] = items
        return items

    async def where(self, container_name: str, **equals: Any) -> list[dict[str, Any]]:
        rows = await self.all(container_name)
        return [row for row in rows if all(row.get(key) == value for key, value in equals.items())]

    async def by_id(self, container_name: str, item_id: str) -> dict[str, Any] | None:
        for row in await self.all(container_name):
            if row.get("id") == item_id:
                return row
        return None

    async def by_ids(self, container_name: str, ids: list[str]) -> list[dict[str, Any]]:
        wanted = set(ids)
        return [row for row in await self.all(container_name) if row.get("id") in wanted]


_repository: GroceryRepository | None = None


async def get_repository() -> GroceryRepository:
    global _repository
    if _repository is None:
        _repository = GroceryRepository()
        await _repository.initialize()
    return _repository
