"""Verify provisioned Azure data resources for the grocery disruption demo.

Checks that the expected Cosmos DB containers, knowledge blob container, and AI
Search index exist. Uses DefaultAzureCredential only; no keys or secrets are read.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

EXPECTED_CONTAINERS = {
    "products",
    "suppliers",
    "warehouses",
    "stores",
    "inventory",
    "demandForecast",
    "substitutes",
    "commitments",
    "promotions",
    "replenishmentSchedule",
    "pastDisruptions",
    "playbooks",
    "stakeholders",
    "signals",
}

# Databricks signal contract: the signals container is the durable handoff point
# for any future lakehouse/MCP signal publisher, and remains partitioned by /partitionKey.


def main() -> int:
    credential = DefaultAzureCredential()
    checks = [verify_cosmos(credential), verify_search(credential), verify_storage(credential)]
    ok = all(checks)
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def verify_cosmos(credential: DefaultAzureCredential) -> bool:
    from azure.cosmos import CosmosClient

    endpoint = os.getenv("COSMOS_ENDPOINT", "").strip()
    database_name = os.getenv("COSMOS_DATABASE", "GroceryDisruptionDB")
    if not endpoint:
        print("Cosmos: SKIP (COSMOS_ENDPOINT is not set)")
        return False

    client = CosmosClient(endpoint, credential=credential)
    database = client.get_database_client(database_name)
    actual = {container["id"] for container in database.list_containers()}
    missing = sorted(EXPECTED_CONTAINERS - actual)
    extra = sorted(actual - EXPECTED_CONTAINERS)
    if missing:
        print(f"Cosmos: FAIL missing containers: {', '.join(missing)}")
        return False
    print(f"Cosmos: OK {database_name} has {len(EXPECTED_CONTAINERS)} expected containers")
    if extra:
        print(f"Cosmos: note extra containers: {', '.join(extra)}")
    return True


def verify_search(credential: DefaultAzureCredential) -> bool:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.search.documents.indexes import SearchIndexClient

    endpoint = os.getenv("SEARCH_ENDPOINT", "").strip().rstrip("/")
    index_name = os.getenv("SEARCH_INDEX_NAME", "grocery-disruption-knowledge")
    if not endpoint:
        print("Search: SKIP (SEARCH_ENDPOINT is not set)")
        return False

    client = SearchIndexClient(endpoint=endpoint, credential=credential)
    try:
        client.get_index(index_name)
    except ResourceNotFoundError:
        print(f"Search: FAIL missing index {index_name}")
        return False
    print(f"Search: OK index {index_name} exists")
    return True


def verify_storage(credential: DefaultAzureCredential) -> bool:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.storage.blob import BlobServiceClient

    endpoint = os.getenv("STORAGE_BLOB_ENDPOINT", "").strip()
    container_name = os.getenv("KNOWLEDGE_CONTAINER", "grocery-knowledge")
    if not endpoint:
        print("Storage: SKIP (STORAGE_BLOB_ENDPOINT is not set)")
        return False

    client = BlobServiceClient(account_url=endpoint, credential=credential)
    container = client.get_container_client(container_name)
    try:
        container.get_container_properties()
    except ResourceNotFoundError:
        print(f"Storage: FAIL missing blob container {container_name}")
        return False
    print(f"Storage: OK blob container {container_name} exists")
    return True


if __name__ == "__main__":
    sys.exit(main())
