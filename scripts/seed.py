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

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KNOWLEDGE = DATA / "knowledge"

load_dotenv(ROOT / ".env", override=False)

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
    from azure.cosmos import CosmosClient, PartitionKey

    endpoint = os.environ["COSMOS_ENDPOINT"]
    database_name = os.getenv("COSMOS_DATABASE", "GroceryDisruptionDB")

    client = CosmosClient(endpoint, credential=DefaultAzureCredential())
    database = client.create_database_if_not_exists(id=database_name)

    total = 0
    for container_name, filename in CONTAINER_FILES.items():
        path = DATA / filename
        if not path.exists():
            raise FileNotFoundError(f"Required seed file is missing: {path}")

        items = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError(f"{path} must contain a JSON array")

        container = database.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path=PARTITION_KEY_PATH),
        )
        written = 0
        for item in items:
            if "id" not in item or "partitionKey" not in item:
                raise ValueError(f"{path} contains an item without id or partitionKey")
            container.upsert_item(item)
            written += 1
        total += written
        print(f"  {container_name}: {written} documents")
    print(f"Cosmos seeding complete: {total} documents.")


def seed_search() -> None:
    from azure.identity import get_bearer_token_provider
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
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import BlobServiceClient, ContentSettings
    from openai import AzureOpenAI

    endpoint = os.environ["SEARCH_ENDPOINT"]
    index_name = os.getenv("SEARCH_INDEX_NAME", "grocery-disruption-knowledge")
    blob_endpoint = os.environ["STORAGE_BLOB_ENDPOINT"]
    container_name = os.getenv("KNOWLEDGE_CONTAINER", "grocery-knowledge")
    credential = DefaultAzureCredential()

    blob_service = BlobServiceClient(account_url=blob_endpoint, credential=credential)
    blob_container = blob_service.get_container_client(container_name)
    try:
        blob_container.create_container()
    except ResourceExistsError:
        pass

    documents = []
    for path in _knowledge_paths():
        text = path.read_text(encoding="utf-8")
        blob_container.upload_blob(
            name=path.name,
            data=text.encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="text/markdown; charset=utf-8"),
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

    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)
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
    index_client.create_or_update_index(index)
    print(f"  index '{index_name}' ready")

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    aoai = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_ad_token_provider=token_provider,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )
    embedding_model = os.getenv("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large")

    print(f"  embedding {len(documents)} chunks ...")
    for batch_start in range(0, len(documents), 16):
        batch = documents[batch_start : batch_start + 16]
        response = aoai.embeddings.create(
            model=embedding_model, input=[doc["content"] for doc in batch]
        )
        for doc, item in zip(batch, response.data):
            doc["contentVector"] = item.embedding

    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    search_client.upload_documents(documents=documents)
    print(f"Search seeding complete: {len(documents)} chunks indexed.")


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


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target in ("all", "cosmos"):
        print("Seeding Cosmos DB ...")
        seed_cosmos()
    if target in ("all", "search"):
        print("Seeding Blob Storage and Azure AI Search ...")
        seed_search()
