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
| `azure.yaml` | Azure Developer CLI service, remote build, deployment hooks, and pipeline configuration. |
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

Open `http://localhost:5173` for the Vite dev server, which proxies the API to `http://127.0.0.1:8000`. A container or production build serves the UI and the API together on a single origin at `http://localhost:8000`.

With no Azure settings the backend uses the bundled JSON datasets and the local Markdown knowledge corpus. Model-backed agents fall back to a deterministic, data-grounded simulation so the full twenty-agent workflow, the approval gate, and every figure on screen still reconcile with the seed data. Simulated payloads are tagged `_executionNote: simulated_offline` so the UI can label them honestly, and the simulator is never used once a model deployment is configured.

Verify the whole solution offline at any time:

```powershell
python tests\test_end_to_end.py
```

## Full Azure provisioning, seed, and deploy

Install Azure Developer CLI (`azd` 1.25.0 or newer), PowerShell 7, and Python
3.11 or newer. Builds run in Azure Container Registry; local Docker is not required.

```powershell
azd auth login --tenant-id 6d84d14b-2ff0-4d99-9ab1-fae089687459
pwsh .\scripts\setup-azd.ps1
azd up
```

The setup command selects environment `grocery-disruption`, subscription
`bb766161-890c-4a8e-9c63-981b510e4e38`, tenant
`6d84d14b-2ff0-4d99-9ab1-fae089687459`, and region `swedencentral`.
Override these with the script's `-EnvironmentName`, `-SubscriptionId`, `-TenantId`,
and `-Location` parameters. These identifiers are configuration, not credentials.

`azd up` provisions infrastructure and identity permissions, builds the image
remotely, and deploys the app plus a manual seed job. The job seeds Cosmos DB and
Search/Blob knowledge and registers Foundry agents inside the app's VNet. Cosmos
and Blob Storage remain private; GitHub needs no data-plane firewall exception. The deployment
then restarts the app and verifies its public UI and API. This creates billable resources
and requires model quota plus permission to assign roles. Review the changes first
with `azd provision --preview`. See [deployment prerequisites and configuration](docs/06-deployment.md).

## Deployment workflows

| Workflow | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Builds the app and image, validates seed data and Bicep/azd configuration, and runs offline workflow and deployment-script tests. |
| `.github/workflows/azure-dev.yml` | Runs `azd provision`, a runtime identity `AcrPull` visibility gate, then `azd deploy` using the `AZURE_CREDENTIALS` repository secret after CI succeeds on a push to `main`, or manually on `main`. |

The split GitHub flow preserves the same provisioning and verification hooks as
`azd up`, but waits for the runtime identity's ACR pull role before image deployment.
The gate only reads Azure RBAC; it does not create identities or change assignments.
Assignment visibility does not prove ACR data-plane token readiness or completed
permission propagation; deployment and postdeploy checks must still succeed.

Configure the `AZURE_CREDENTIALS` repository secret with an approved service
principal's `clientId`, `clientSecret`, `subscriptionId`, and `tenantId`. Set the
matching repository variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, `AZURE_ENV_NAME`, and `AZURE_LOCATION`.
The workflow validates these values, signs Azure CLI in using the secret, and
configures azd to use the same verified CLI identity. It does not use OIDC.

```powershell
gh workflow run azure-dev.yml --repo frkim/GrocerySupplyDisruptionResponse --ref main
```

Never commit the secret or paste it into logs. Rotate exposed or expired values
in GitHub before deployment. Setup, permissions, and an optional future OIDC
migration are described in [the deployment guide](docs/06-deployment.md#github-actions).

## Front-end URL

| Mode | URL |
| --- | --- |
| Local dev server (Vite, proxies the API) | `http://localhost:5173` |
| Local single-origin build or container | `http://localhost:8000` |
| Deployed to Azure Container Apps | `https://<app-name>.<region-id>.azurecontainerapps.io` |

After a successful deployment, retrieve the real front-end URL:

```powershell
azd env get-value APP_URL
```

GitHub Actions prints the verified URL in its run summary. There is no deployed
address until provisioning and deployment succeed.

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
