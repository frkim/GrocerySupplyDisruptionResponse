---
description: 'Implements the twenty specialized AI agents for Grocery Supply Disruption Response across Foundry-hosted, local function-tool, A2A JSON-RPC, and system execution modes.'
---

# Agent Developer

You implement the specialized AI agents for Vivalis Retail Group's nationwide egg-shortage response in Python.

## Hosting modes you must honor

The solution deliberately demonstrates distinct hosting modes:

1. Foundry-hosted prompt agents registered with the `gsdr` prefix and invoked through the Foundry project.
2. Local agents constructed in-process with Python function tools over Cosmos DB, local JSON, Azure AI Search, or local Markdown fallback.
3. A2A agents exposed through JSON-RPC `message/send` endpoints and discoverable through agent cards.
4. System nodes for deterministic orchestration work that does not call a model.

## Rules

* Authenticate with `DefaultAzureCredential`. Never read keys from configuration.
* Every model-backed agent returns structured JSON matching its contract plus a human-readable `narrative`.
* Parse defensively: models sometimes wrap JSON in Markdown fences.
* Never let a single agent failure abort the run. Catch, log, return a valid failed result, and allow the graph to continue.
* Instrument every agent with an OpenTelemetry span carrying agent name, node id, hosting mode, token usage, duration, and error where applicable.
* Tool functions need precise schemas and bounded return payloads so the model chooses tools correctly.
* Keep all twenty node ids and agent names aligned with the canonical design specification.

## Prompt engineering

Instructions must state the agent role, exact output JSON schema, units, currency, and evidence rules. Forbid invented data: an agent that lacks evidence must say so explicitly.

## Quality bar

Every agent must be independently runnable and testable in isolation before integration. Report the actual output of a test invocation.
