"""Stores every Foundry-hosted agent definition in the Microsoft Foundry project.

Run this after deployment (or any prompt/tool change) so the agents are listed in the
Foundry portal without waiting for the first workflow run.

    python scripts/provision_agents.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "backend"))

os.environ.setdefault("FOUNDRY_AGENT_PREFIX", "gsdr")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def wait_for_project_access(settings) -> None:
    """Probe project RBAC before the runtime's optional connection fallback can cache a failure."""
    from azure.ai.projects.aio import AIProjectClient
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity.aio import DefaultAzureCredential
    from app.agents.definitions import AGENTS
    from app.agents.foundry import agent_name_for
    from app.contracts import HostingMode

    if __package__:
        from .deployment_hooks import retry_azure_async
    else:
        from deployment_hooks import retry_azure_async

    async with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.ai_project_endpoint, credential=credential,
    ) as client:
        async def probe():
            connections = [connection async for connection in client.connections.list()]
            if settings.enable_foundry_knowledge and not any(
                connection.name.lower() == settings.knowledge_connection_name.strip().lower()
                and "search" in str(getattr(connection, "type", "")).lower()
                for connection in connections
            ):
                raise RuntimeError("Required Foundry knowledge-search connection is missing.")
            spec = next(spec for spec in AGENTS if spec.hosting_mode is HostingMode.FOUNDRY)
            try:
                async for _ in client.agents.list_versions(agent_name_for(spec), limit=1, order="desc"):
                    break
            except ResourceNotFoundError:
                # No version yet is expected on the first deployment, unlike forbidden access.
                pass

        await retry_azure_async(probe, "Read Foundry project/agent access")


async def main() -> int:
    from app.agents.foundry import close, provision_all
    from app.config import get_settings

    settings = get_settings()
    if not settings.ai_project_endpoint:
        print("AZURE_AI_PROJECT_ENDPOINT is not set; nothing to provision.")
        return 1

    print(f"Project: {settings.ai_project_endpoint}")
    print(f"Model:   {settings.model_deployment}")

    try:
        if os.getenv("GSDR_AZD_HOOK"):
            await wait_for_project_access(settings)
        status = await provision_all()
        agents = status.get("agents", [])
        connection = status.get("knowledgeConnection")
        print(f"Knowledge connection: {connection or 'none'}")
        print(f"\nStored {len(agents)} agent(s):")
        for agent in agents:
            state = "created" if agent["created"] else "reused"
            knowledge = "knowledge" if agent.get("knowledge") else "-"
            print(
                f"  - {agent['agentName']:<38} v{agent['version']:<4} "
                f"tools={agent['toolCount']:<2} {knowledge:<9} {state}"
            )

        errors = status.get("errors", {})
        if errors:
            print("\nErrors:")
            print(json.dumps(errors, indent=2))
            return 2
        if not status.get("enabled") or not agents:
            print("Foundry provisioning was disabled or produced no agents.")
            return 1
        if os.getenv("GSDR_AZD_HOOK") and settings.enable_foundry_knowledge and not connection:
            print("Foundry agents were not connected to the required knowledge index.")
            return 1
        return 0
    finally:
        await close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
