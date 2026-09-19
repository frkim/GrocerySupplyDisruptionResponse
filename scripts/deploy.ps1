# Builds the container image in ACR and deploys/updates the Container App.
# Usage:  pwsh ./scripts/deploy.ps1

$ErrorActionPreference = 'Stop'

$ResourceGroup = 'rg-grocery-disruption'
$Location = 'swedencentral'
$CoreDeployment = 'gsdr-core'
$ImageRepository = 'grocery-disruption'
$Root = Split-Path -Parent $PSScriptRoot

Write-Host '==> Ensuring resource group exists' -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location --output none
if ($LASTEXITCODE -ne 0) { throw 'Resource group creation failed.' }

Write-Host '==> Deploying core infrastructure' -ForegroundColor Cyan
az deployment group create `
    --resource-group $ResourceGroup `
    --name $CoreDeployment `
    --template-file "$Root\infra\main.bicep" `
    --parameters location=$Location namePrefix=gsdr `
    --output none
if ($LASTEXITCODE -ne 0) { throw 'Core deployment failed.' }

Write-Host '==> Reading core deployment outputs' -ForegroundColor Cyan
$outputs = az deployment group show `
    --resource-group $ResourceGroup `
    --name $CoreDeployment `
    --query properties.outputs -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Reading core deployment outputs failed.' }

$acrName = $outputs.acrName.value
$acrLoginServer = $outputs.acrLoginServer.value
$tag = (git rev-parse --short HEAD 2>$null)
if (-not $tag) { $tag = "v$(Get-Date -Format 'yyyyMMddHHmmss')" }
$image = "$acrLoginServer/$ImageRepository`:$tag"

Write-Host "==> Building image $image" -ForegroundColor Cyan
az acr build `
    --registry $acrName `
    --image "$ImageRepository`:$tag" `
    --image "$ImageRepository`:latest" `
    --file "$Root\Dockerfile" `
    $Root
if ($LASTEXITCODE -ne 0) { throw 'Image build failed.' }

Write-Host '==> Deploying container app' -ForegroundColor Cyan
$appOut = az deployment group create `
    --resource-group $ResourceGroup `
    --name "gsdr-app-$tag" `
    --template-file "$Root\infra\app.bicep" `
    --parameters `
        namePrefix=gsdr `
        containerAppEnvironmentId=$($outputs.containerAppEnvironmentId.value) `
        acrLoginServer=$acrLoginServer `
        containerImage=$image `
        identityId=$($outputs.identityId.value) `
        identityClientId=$($outputs.identityClientId.value) `
        aiProjectEndpoint=$($outputs.aiProjectEndpoint.value) `
        openAiEndpoint=$($outputs.openAiEndpoint.value) `
        modelDeploymentName=$($outputs.modelDeploymentName.value) `
        embeddingDeploymentName=$($outputs.embeddingDeploymentName.value) `
        cosmosEndpoint=$($outputs.cosmosEndpoint.value) `
        cosmosDatabase=GroceryDisruptionDB `
        searchEndpoint=$($outputs.searchEndpoint.value) `
        searchIndexName=grocery-disruption-knowledge `
        storageBlobEndpoint=$($outputs.storageBlobEndpoint.value) `
        appInsightsConnectionString=$($outputs.appInsightsConnectionString.value) `
    --query properties.outputs -o json
if ($LASTEXITCODE -ne 0) { throw 'Container app deployment failed.' }

$appUrl = ($appOut | ConvertFrom-Json).appUrl.value
Write-Host ''
Write-Host "Front-end application URL: $appUrl" -ForegroundColor Green
Write-Host "Image tag: $tag" -ForegroundColor Green
