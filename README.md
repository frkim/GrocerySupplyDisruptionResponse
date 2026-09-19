# Grocery Supply Disruption Response

Grocery Supply Disruption Response is an agentic response console for a fictional national grocery retailer: twenty specialized AI agents detect, assess and coordinate Vivalis Retail Group's response to a nationwide egg shortage caused by a highly pathogenic avian influenza outbreak.

## Scenario

Vivalis Retail Group operates 1,180 stores across hypermarket, supermarket, convenience, and drive/click-and-collect formats, supplied by 8 regional distribution centres. The reference incident starts when avian influenza cuts national shell-egg production, creating a ~38% supply shortfall while demand surges by ~44%. Days of cover collapse unevenly across `NORTH`, `SOUTH`, `EAST`, `WEST`, and `CENTRE`; live promotions are still active; and private-label bakery and ready-meal SKUs that consume liquid or industrial egg are exposed.

## Orchestration DAG

```text
signal_normalizer
        |
situation_assessment
        |
historical_knowledge
        |
        +--> demand_forecast --------+
        +--> network_inventory ------+   concurrent impact fan-out
        +--> financial_impact -------+--> impact_synthesis
        +--> store_impact -----------+
                                      |
                              response_planner
                                      |
        +--> sourcing_procurement ----+
        +--> allocation_fairness -----+
        +--> substitution_assortment -+   concurrent validation fan-out
        +--> pricing_compliance ------+--> scenario_evaluation
        +--> logistics_cold_chain ----+
                                      |
                              deliberation (conditional)
                                      |
                              executive_gate (human gate)
                              /                         \
                 store_operations          customer_communication
                              \                         /
                              executive_briefing
```

## Orchestration patterns

| Pattern | Where it appears |
| --- | --- |
| Sequential spine | `signal_normalizer` -> `situation_assessment` -> `historical_knowledge` -> `impact_synthesis` -> `response_planner` -> `scenario_evaluation` -> `deliberation` -> `executive_gate` -> `executive_briefing`. |
| Concurrent fan-out/fan-in | Four impact agents after `historical_knowledge`, then five validation agents after `response_planner`. |
| Conditional routing | `deliberation` runs only when `scenario_evaluation` returns `closeCall` or the top scores are within the configured threshold. |
| Human-in-the-loop | `executive_gate` emits `gate_awaiting` and waits for `POST /api/runs/{run_id}/decision` or timeout. |
| Graceful degradation | Node failures become failed `NodeResult` records; joins continue with gaps recorded instead of aborting the run. |

## Twenty-agent roster

| node_id | Agent | What it decides | Hosting mode |
| --- | --- | --- | --- |
| `signal_normalizer` | `ShortageSignalNormalizer` | Normalizes the incoming shortage signal, computes severity, and creates the incident baseline. | `system` |
| `situation_assessment` | `SituationAssessmentAgent` | Establishes scope, affected SKUs, DCs, store clusters, days of cover, and root cause. | `foundry` |
| `historical_knowledge` | `HistoricalKnowledgeAgent` | Retrieves prior HPAI shortages, playbooks, policy constraints, and lessons learned. | `foundry` |
| `demand_forecast` | `DemandForecastAgent` | Quantifies baseline versus surge demand by SKU and region. | `local` |
| `network_inventory` | `NetworkInventoryAgent` | Assesses on-hand, committed, in-transit, safety-stock, and cover positions. | `local` |
| `financial_impact` | `FinancialImpactAgent` | Quantifies revenue, margin, penalty, promotion, and sourcing cost exposure. | `a2a` |
| `store_impact` | `StoreImpactAgent` | Identifies store clusters, shelf availability, purchase-limit needs, and service risks. | `a2a` |
| `impact_synthesis` | `ImpactSynthesisAgent` | Joins the four impact views into one urgency and exposure picture. | `foundry` |
| `response_planner` | `ResponsePlannerAgent` | Produces exactly four response options A through D. | `foundry` |
| `sourcing_procurement` | `SourcingProcurementAgent` | Validates supplier qualification, capacity, pricing, lead time, and import feasibility. | `a2a` |
| `allocation_fairness` | `AllocationFairnessAgent` | Validates fair-share allocation across regions, formats, and commitments. | `local` |
| `substitution_assortment` | `SubstitutionAssortmentAgent` | Validates substitutes, reformulation, assortment edits, labelling impact, and acceptance. | `local` |
| `pricing_compliance` | `PricingComplianceAgent` | Validates pricing actions, consumer-protection rules, messages, and approvals. | `a2a` |
| `logistics_cold_chain` | `LogisticsColdChainAgent` | Validates chilled capacity, transfers, inbound doors, cross-dock use, and transport constraints. | `a2a` |
| `scenario_evaluation` | `ScenarioEvaluationAgent` | Scores options on financial, operational, customer, compliance, and sustainability dimensions. | `foundry` |
| `deliberation` | `DeliberationAgent` | Runs structured debate when evaluation is a close call. | `foundry` |
| `executive_gate` | `ExecutiveApprovalGate` | Suspends the run for an executive option decision or timeout auto-approval. | `system` |
| `store_operations` | `StoreOperationsAgent` | Turns the approved option into store operating actions, limits, replenishment tasks, and KPIs. | `foundry` |
| `customer_communication` | `CustomerCommunicationAgent` | Creates customer, colleague, signage, and digital-channel communication guidance. | `foundry` |
| `executive_briefing` | `ExecutiveBriefingAgent` | Produces the final decision record, board-level summary, actions, risks, and outcomes. | `foundry` |

## Agent hosting and grounding

| Hosting mode | How it works |
| --- | --- |
| `foundry` | Foundry-hosted prompt agents are stored in the Foundry project with instructions and tool schemas. The runner falls back to the shared model path when hosted execution is unavailable. |
| `local` | In-process agents run inside FastAPI and call Python function tools directly. |
| `a2a` | Agents are invoked through Agent-to-Agent JSON-RPC `message/send` and advertise agent cards under `/a2a/{agent_name}/.well-known/agent-card.json`. |
| `system` | Deterministic workflow nodes, such as signal normalization and the executive gate, do not call a model. |

Grounding comes from 17 function tools over the domain data and retrieval over the knowledge corpus in Azure AI Search. In degraded mode, the same tool names read bundled JSON and local Markdown content.

## Repository layout

| Path | Purpose |
| --- | --- |
| `README.md` | Top-level product overview and quickstart. |
| `docs/` | Architecture, agent, orchestration, data, deployment, and extension documentation. |
| `data/` | Bundled JSON seed datasets and the `data/knowledge` Markdown corpus. |
| `infra/` | Bicep for Foundry, Azure OpenAI, Cosmos DB, Search, Storage, Container Apps, ACR, identity, and observability. |
| `scripts/` | Provisioning, seeding, deployment, and verification helpers. |
| `src/backend/` | FastAPI API, contracts, orchestration engine, agent runner, tools, data access, and A2A endpoints. |
| `src/frontend/` | React control-room UI. |
| `.github/agents/` | Build-agent instructions for repository workstreams. |
| `.github/workflows/` | CI and Azure deployment workflows. |

## Quickstart: local zero-Azure mode

The workstation package managers are expected to use the approved organization feeds. Do not override them with public registries.

```powershell
# From the repository root
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src\backend\requirements.txt
Set-Location src\backend
..\..\.venv\Scripts\python.exe -c "from app.main import app; print(app.title)"
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell window:

```powershell
Set-Location src\frontend
npm install
npm run dev
```

Open `http://localhost:5173`. With no Azure settings, the backend uses bundled JSON and local Markdown knowledge. Model-backed agents report degraded execution until Azure OpenAI is configured, but the app, graph, scenario metadata, and local data paths still start without cloud services.

## Full Azure provisioning, seed, and deploy

```powershell
az login
az group create --name rg-grocery-disruption --location swedencentral
az deployment group create `
  --resource-group rg-grocery-disruption `
  --name gsdr-core `
  --template-file infra\main.bicep `
  --parameters infra\main.parameters.json

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src\backend\requirements.txt
.\.venv\Scripts\python.exe scripts\seed.py
pwsh .\scripts\deploy.ps1
```

## Deployment workflows

| Workflow | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Restores dependencies from approved feeds, validates backend import/compile checks, builds the frontend, and runs local-safe tests. |
| `.github/workflows/deploy.yml` | Builds the container image, deploys the Azure Container App, and verifies `/api/health`. |

`deploy.yml` requires one repository secret named `AZURE_CREDENTIALS` containing the JSON output shape produced by `az ad sp create-for-rbac --sdk-auth`. Use placeholder values only in documentation:

```json
{
  "clientId": "00000000-0000-0000-0000-000000000000",
  "client credential field omitted": "placeholder only",
  "subscriptionId": "00000000-0000-0000-0000-000000000000",
  "tenantId": "00000000-0000-0000-0000-000000000000",
  "activeDirectoryEndpointUrl": "https://login.microsoftonline.com",
  "resourceManagerEndpointUrl": "https://management.azure.com/",
  "activeDirectoryGraphResourceId": "https://graph.windows.net/",
  "sqlManagementEndpointUrl": "https://management.core.windows.net:8443/",
  "galleryEndpointUrl": "https://gallery.azure.com/",
  "managementEndpointUrl": "https://management.core.windows.net/"
}
```

## Security note

All Azure access in application code uses `DefaultAzureCredential` and managed identity where deployed. The application does not read service keys or client secrets from committed files.

## Not a real retailer

Vivalis Retail Group, every supplier, every SKU, every store cluster, and all incident data in this repository are fictional and exist only for the demo.

## Documentation

* [Documentation index](docs/README.md)
* [Business scenario](docs/01-business-scenario.md)
* [Architecture](docs/02-architecture.md)
* [Agents](docs/03-agents.md)
* [Orchestration](docs/04-orchestration.md)
* [Data model](docs/05-data-model.md)
* [Deployment](docs/06-deployment.md)
* [Extending](docs/07-extending.md)
