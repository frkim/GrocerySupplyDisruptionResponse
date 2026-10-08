"""Runtime configuration. Every Azure dependency is optional so the app still starts
(and reports degraded capability) when a backing service is unreachable."""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv(override=False)


def _flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def deployment_supports_temperature(deployment: str) -> bool:
    return not deployment.lower().startswith(("gpt-5", "o1", "o3", "o4"))


class Settings:
    def __init__(self) -> None:
        self.openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        self.ai_project_endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").rstrip("/")
        self.model_deployment = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-4o")
        self.model_max_concurrency = int(os.getenv("MODEL_MAX_CONCURRENCY", "6"))
        # Display translation gets its own slots (and optionally a faster deployment) so it
        # never queues behind a running workflow. An empty name reuses the chat deployment.
        self.translation_deployment = (
            os.getenv("TRANSLATION_MODEL_DEPLOYMENT_NAME", "").strip() or self.model_deployment
        )
        self.translation_max_concurrency = int(os.getenv("TRANSLATION_MAX_CONCURRENCY", "4"))
        self.embedding_deployment = os.getenv("EMBEDDING_DEPLOYMENT_NAME", "text-embedding-3-large")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")

        self.cosmos_endpoint = os.getenv("COSMOS_ENDPOINT", "")
        self.cosmos_database = os.getenv("COSMOS_DATABASE", "GroceryDisruptionDB")

        self.search_endpoint = os.getenv("SEARCH_ENDPOINT", "").rstrip("/")
        self.search_index = os.getenv("SEARCH_INDEX_NAME", "grocery-disruption-knowledge")

        self.storage_blob_endpoint = os.getenv("STORAGE_BLOB_ENDPOINT", "")
        self.knowledge_container = os.getenv("KNOWLEDGE_CONTAINER", "grocery-knowledge")

        self.appinsights_connection = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

        self.enable_deliberation = _flag("ENABLE_DELIBERATION", True)
        self.enable_foundry_hosted = _flag("ENABLE_FOUNDRY_HOSTED_AGENTS", True)

        # Agents are stored in the Foundry project so the portal lists them before any run.
        self.provision_foundry_agents = _flag("PROVISION_FOUNDRY_AGENTS", True)
        self.foundry_agent_prefix = os.getenv("FOUNDRY_AGENT_PREFIX", "gsdr")
        self.foundry_max_tool_rounds = int(os.getenv("FOUNDRY_MAX_TOOL_ROUNDS", "4"))

        # Optional MCP server published to every hosted agent alongside the function tools.
        self.mcp_server_label = os.getenv("MCP_SERVER_LABEL", "")
        self.mcp_server_url = os.getenv("MCP_SERVER_URL", "").rstrip("/")

        # Native Foundry grounding on the knowledge index, via a project connection.
        self.enable_foundry_knowledge = _flag("ENABLE_FOUNDRY_KNOWLEDGE", True)
        self.knowledge_connection_name = os.getenv("KNOWLEDGE_CONNECTION_NAME", "knowledge-search")
        self.knowledge_query_type = os.getenv("KNOWLEDGE_QUERY_TYPE", "simple")
        self.knowledge_top_k = int(os.getenv("KNOWLEDGE_TOP_K", "5"))

        # Prompt and completion content in traces is opt-in because it carries business data.
        self.record_prompt_content = _flag("GEN_AI_CONTENT_RECORDING", False)

        # Self-address used for genuine A2A calls over HTTP.
        self.self_base_url = os.getenv("SELF_BASE_URL", "http://127.0.0.1:8000")

        self.request_timeout = float(os.getenv("AGENT_TIMEOUT_SECONDS", "180"))
        self.gate_timeout = float(os.getenv("GATE_TIMEOUT_SECONDS", "900"))

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_endpoint)

    @property
    def supports_temperature(self) -> bool:
        return deployment_supports_temperature(self.model_deployment)

    @property
    def has_cosmos(self) -> bool:
        return bool(self.cosmos_endpoint)

    @property
    def has_search(self) -> bool:
        return bool(self.search_endpoint)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

