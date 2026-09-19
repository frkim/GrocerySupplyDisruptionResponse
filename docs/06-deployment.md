# Deployment

## Provisioning with Bicep

The long-lived deployment uses the product naming defaults from the design specification: resource group `rg-grocery-disruption`, core deployment `gsdr-core`, image repository `grocery-disruption`, Cosmos database `GroceryDisruptionDB`, Search index `grocery-disruption-knowledge`, blob container `grocery-knowledge`, Foundry agent prefix `gsdr`, and Bicep token prefix `gsdr`.

```powershell
az login
az group create --name rg-grocery-disruption --location swedencentral
az deployment group create `
  --resource-group rg-grocery-disruption `
  --name gsdr-core `
  --template-file infra\main.bicep `
  --parameters infra\main.parameters.json
```

The core deployment provisions managed identity, Azure Container Registry, Container Apps environment, Foundry/Azure OpenAI resources, Cosmos DB, Azure AI Search, Storage, Application Insights, Log Analytics, and RBAC.

## Seed Cosmos DB and Azure AI Search

After core provisioning, seed the 14 JSON datasets into Cosmos DB and index the 8 knowledge documents into Azure AI Search:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src\backend\requirements.txt
.\.venv\Scripts\python.exe scripts\seed.py
```

The seed path is idempotent: records are upserted by `id`, and knowledge chunks are created from `data\knowledge\*.md` for the `grocery-disruption-knowledge` index.

## Container build and application deployment

The application is one container. The frontend is built first, copied into the backend static directory, and served by FastAPI from the same origin as the API.

```powershell
pwsh .\scripts\deploy.ps1
```

The deployment script is expected to read `gsdr-core` outputs, build the image in ACR using the `grocery-disruption` repository, deploy `infra\app.bicep`, and emit the Container App URL.

## GitHub workflows

| Workflow | Responsibility |
| --- | --- |
| `.github/workflows/ci.yml` | Local-safe validation: backend import/compile, frontend dependency restore, `npm run build`, and tests that do not require credentials. |
| `.github/workflows/deploy.yml` | Azure login, read `gsdr-core` outputs, build the image, deploy the Container App, and poll `/api/health`. |

`deploy.yml` requires a single repository secret, `AZURE_CREDENTIALS`, containing this placeholder JSON shape from `az ad sp create-for-rbac --sdk-auth`:

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

Never commit a real value. Store the JSON only as the GitHub secret.

## Finding the deployed front-end URL

Use one of these approaches after deployment:

```powershell
az containerapp list --resource-group rg-grocery-disruption --query "[].{name:name,url:properties.configuration.ingress.fqdn}" -o table
```

or inspect the deployment output from the app deployment:

```powershell
az deployment group show `
  --resource-group rg-grocery-disruption `
  --name <app-deployment-name> `
  --query properties.outputs.appUrl.value -o tsv
```

Open the returned HTTPS URL. The same host serves the UI, `/api/health`, `/api/scenario`, `/api/runs/stream`, and A2A endpoints.

## Troubleshooting

| Symptom | Likely cause | Check | Fix |
| --- | --- | --- | --- |
| `/api/health` does not return 200 | Container revision did not start | Container App logs and revision status | Fix startup exception, rebuild, redeploy. |
| `openAiConfigured` is false | Azure OpenAI endpoint not passed to app | App environment variables from deployment outputs | Redeploy `infra\app.bicep` with `openAiEndpoint`. |
| Data source is local in Azure | Cosmos endpoint or RBAC missing | `COSMOS_ENDPOINT`, `GroceryDisruptionDB`, managed identity roles | Correct outputs or role assignment, restart revision. |
| Knowledge source is local | Search endpoint, index, or role missing | `SEARCH_ENDPOINT`, `grocery-disruption-knowledge`, Search roles | Rerun seed and verify Search permissions. |
| Foundry agents use fallback | Foundry endpoint, agent provisioning, or project role issue | `/api/foundry/agents` and startup logs | Re-provision agents and verify `gsdr` prefix resources. |
| A2A nodes fail | `SELF_BASE_URL` does not resolve inside container | Logs from `/a2a/{agent_name}` calls | Use `http://127.0.0.1:8000` for same-container topology. |
| Gate appears stuck | Run is awaiting executive input | Latest SSE event is `gate_awaiting` | Submit `POST /api/runs/{run_id}/decision` or wait for timeout. |
| Workflow login fails | `AZURE_CREDENTIALS` missing or malformed | GitHub Actions secret configuration | Replace with valid sdk-auth JSON in the secret store only. |
