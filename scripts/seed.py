"""Seed Cosmos DB, Blob Storage, and Azure AI Search for the grocery disruption demo.

Run after provisioning:  python scripts/seed.py
Reads endpoints from the environment (see .env.example) and authenticates with
DefaultAzureCredential, so no keys or secrets are required.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if __package__:
    from .deployment_hooks import TRANSIENT_STATUSES, retry_azure
else:
    from deployment_hooks import TRANSIENT_STATUSES, retry_azure

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KNOWLEDGE = DATA / "knowledge"

CONTAINER_FILES = {
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

KNOWLEDGE_FILES = [
    "2022-avian-influenza-postmortem.md",
    "fair-share-allocation-policy.md",
    "warehouse-allocation-playbook.md",
    "egg-substitution-and-reformulation-guide.md",
    "pricing-and-consumer-protection-rules.md",
    "food-safety-and-avian-influenza-regulation.md",
    "store-communication-and-signage-standards.md",
    "responsible-sourcing-and-animal-welfare-standards.md",
]

# Databricks signal contract: upstream lakehouse integrations can still publish
# records matching data/signals.json; this repo seeds that contract into Cosmos.
PARTITION_KEY_PATH = "/partitionKey"


def seed_cosmos() -> None:
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ["COSMOS_ENDPOINT"]
    database_name = os.getenv("COSMOS_DATABASE", "GroceryDisruptionDB")

    with DefaultAzureCredential() as credential, CosmosClient(endpoint, credential=credential) as client:
        database = client.get_database_client(database_name)
        retry_azure(database.read, f"Read Cosmos database {database_name}")
        total = 0
        for container_name, filename in CONTAINER_FILES.items():
            path = DATA / filename
            if not path.exists():
                raise FileNotFoundError(f"Required seed file is missing: {path}")

            items = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                raise ValueError(f"{path} must contain a JSON array")
            if any(not isinstance(item, dict) or "id" not in item or "partitionKey" not in item for item in items):
                raise ValueError(f"{path} contains an item without id or partitionKey")

            # ARM owns databases/containers. Cosmos data-plane RBAC cannot create them.
            container = database.get_container_client(container_name)
            properties = retry_azure(container.read, f"Read Cosmos container {container_name}")
            if properties.get("partitionKey", {}).get("paths") != [PARTITION_KEY_PATH]:
                raise ValueError(f"Cosmos container {container_name} must use {PARTITION_KEY_PATH}")
            for item in items:
                retry_azure(lambda: container.upsert_item(item), f"Upsert Cosmos {container_name}/{item['id']}")
            total += len(items)
            print(f"  {container_name}: {len(items)} documents")
    print(f"Cosmos seeding complete: {total} documents.")


def seed_search() -> None:
    from contextlib import ExitStack

    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )
    from azure.storage.blob import BlobServiceClient, ContentSettings
    from openai import AzureOpenAI

    endpoint = os.environ["SEARCH_ENDPOINT"]
    index_name = os.getenv("SEARCH_INDEX_NAME", "grocery-disruption-knowledge")
    blob_endpoint = os.environ["STORAGE_BLOB_ENDPOINT"]
    container_name = os.getenv("KNOWLEDGE_CONTAINER", "grocery-knowledge")
    with ExitStack() as stack:
        credential = stack.enter_context(DefaultAzureCredential())
        blob_service = stack.enter_context(BlobServiceClient(account_url=blob_endpoint, credential=credential))
        blob_container = blob_service.get_container_client(container_name)
        retry_azure(blob_container.get_container_properties, f"Read blob container {container_name}")

        documents = []
        for path in _knowledge_paths():
            text = path.read_text(encoding="utf-8")
            retry_azure(
                lambda: blob_container.upload_blob(
                    name=path.name,
                    data=text.encode("utf-8"),
                    overwrite=True,
                    content_settings=ContentSettings(content_type="text/markdown; charset=utf-8"),
                ),
                f"Upload knowledge blob {path.name}",
            )
            for position, chunk in enumerate(_chunk(text)):
                documents.append(
                    {
                        "id": f"{path.stem}-{position}".replace("_", "-"),
                        "title": path.stem.replace("-", " "),
                        "content": chunk,
                        "sourceFile": path.name,
                    }
                )
        print(f"  uploaded {len(KNOWLEDGE_FILES)} knowledge documents to {container_name}")

        index_client = stack.enter_context(SearchIndexClient(endpoint=endpoint, credential=credential))
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SimpleField(name="sourceFile", type=SearchFieldDataType.String, filterable=True),
            SearchField(
                name="contentVector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=3072,
                vector_search_profile_name="default-profile",
            ),
        ]
        index = SearchIndex(
            name=index_name,
            fields=fields,
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="default-algorithm")],
                profiles=[
                    VectorSearchProfile(
                        name="default-profile", algorithm_configuration_name="default-algorithm"
                    )
                ],
            ),
        )
        retry_azure(lambda: index_client.create_or_update_index(index), f"Create/update Search index {index_name}")
        print(f"  index '{index_name}' ready")

        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        aoai = stack.enter_context(AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        ))
        embedding_model = os.getenv("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large")

        print(f"  embedding {len(documents)} chunks ...")
        for batch_start in range(0, len(documents), 16):
            batch = documents[batch_start : batch_start + 16]
            response = retry_azure(
                lambda: aoai.embeddings.create(model=embedding_model, input=[doc["content"] for doc in batch]),
                "Generate knowledge embeddings",
            )
            if len(response.data) != len(batch) or {item.index for item in response.data} != set(range(len(batch))):
                raise ValueError("Embedding response does not match the requested batch.")
            for item in response.data:
                if len(item.embedding) != 3072:
                    raise ValueError("Embedding deployment must produce 3072-dimensional vectors.")
                batch[item.index]["contentVector"] = item.embedding

        search_client = stack.enter_context(SearchClient(endpoint=endpoint, index_name=index_name, credential=credential))
        upload_search_documents(search_client, documents)
    print(f"Search seeding complete: {len(documents)} chunks indexed.")


class SearchUploadError(RuntimeError):
    def __init__(self, failures):
        self.status_code = next(
            (result.status_code for result in failures if result.status_code not in TRANSIENT_STATUSES),
            failures[0].status_code,
        )
        detail = "; ".join(
            f"{result.key}: HTTP {result.status_code} {result.error_message or ''}" for result in failures
        )
        super().__init__("Search document upload failed: " + detail)


def upload_search_documents(client, documents: list[dict]) -> None:
    pending = {document["id"]: document for document in documents}
    if not pending or len(pending) != len(documents):
        raise ValueError("Search upload requires nonempty documents with unique IDs.")

    def upload():
        results = client.upload_documents(documents=list(pending.values()))
        if len(results) != len(pending) or {result.key for result in results} != set(pending):
            raise RuntimeError("Search upload did not return a result for every document.")
        failures = []
        for result in results:
            if result.succeeded:
                del pending[result.key]
            else:
                failures.append(result)
        if failures:
            raise SearchUploadError(failures)

    retry_azure(upload, "Upload Search documents")


def _knowledge_paths() -> list[Path]:
    paths = [KNOWLEDGE / filename for filename in KNOWLEDGE_FILES]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Required knowledge files are missing: " + ", ".join(missing))
    return paths


def _chunk(text: str, size: int = 1400) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 > size and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", choices=("all", "cosmos", "search"), default="all")
    target = parser.parse_args(argv).target
    if not os.getenv("GSDR_AZD_HOOK"):
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    required = []
    if target in ("all", "cosmos"):
        required.append("COSMOS_ENDPOINT")
    if target in ("all", "search"):
        required.extend(("SEARCH_ENDPOINT", "STORAGE_BLOB_ENDPOINT", "AZURE_OPENAI_ENDPOINT"))
    missing = [key for key in required if not os.getenv(key, "").strip()]
    if missing:
        raise ValueError("Missing seed configuration: " + ", ".join(missing))
    if target in ("all", "cosmos"):
        print("Seeding Cosmos DB ...")
        seed_cosmos()
    if target in ("all", "search"):
        print("Seeding Blob Storage and Azure AI Search ...")
        seed_search()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
