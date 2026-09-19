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

from app.agents.foundry import close, provision_all  # noqa: E402
from app.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


async def main() -> int:
    settings = get_settings()
    if not settings.ai_project_endpoint:
        print("AZURE_AI_PROJECT_ENDPOINT is not set; nothing to provision.")
        return 1

    print(f"Project: {settings.ai_project_endpoint}")
    print(f"Model:   {settings.model_deployment}")

    status = await provision_all()
    try:
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
        return 0 if agents else 1
    finally:
        await close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
