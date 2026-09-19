targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('azd environment name. Reuse the same environment and resource group to preserve resource names.')
param environmentName string = 'grocery-disruption'

@description('Azure region for all resources; model availability and quota vary by region.')
param location string = 'swedencentral'

@description('Optional existing resource group name. Defaults to rg-<environmentName>.')
param resourceGroupName string = ''

@minLength(2)
@maxLength(8)
@description('Lowercase alphanumeric prefix applied to the existing resource naming scheme.')
param namePrefix string = 'gsdr'

@description('Object ID of the azd deployment user or CI service principal; not an application/client ID.')
param principalId string = ''

param modelDeploymentName string = 'gpt-4o'
param modelName string = 'gpt-4o'
param modelVersion string = '2024-11-20'
param modelSku string = 'GlobalStandard'
@minValue(1)
param modelCapacity int = 100

param embeddingDeploymentName string = 'text-embedding-3-large'
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'
param embeddingSku string = 'Standard'
@minValue(1)
param embeddingCapacity int = 50

param searchIndexName string = 'grocery-disruption-knowledge'
param foundryAgentPrefix string = 'gsdr'
param knowledgeConnectionName string = 'knowledge-search'

var tags = {
  'azd-env-name': environmentName
}
var appName = '${namePrefix}-app'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : 'rg-${environmentName}'
  location: location
  tags: tags
}

// The app is deployed separately by azd from app.bicep + app.parameters.json.
// Provisioning never writes a placeholder over the currently deployed image.
module core './core.bicep' = {
  name: 'core'
  scope: rg
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    principalId: principalId
    modelDeploymentName: modelDeploymentName
    modelName: modelName
    modelVersion: modelVersion
    modelSku: modelSku
    modelCapacity: modelCapacity
    embeddingDeploymentName: embeddingDeploymentName
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingSku: embeddingSku
    embeddingCapacity: embeddingCapacity
    knowledgeConnectionName: knowledgeConnectionName
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = core.outputs.acrLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = core.outputs.acrName
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = core.outputs.containerAppEnvironmentId
output AZURE_CONTAINER_APP_NAME string = appName
output AZURE_SEED_JOB_NAME string = '${appName}-seed'
output AZURE_AI_PROJECT_ENDPOINT string = core.outputs.aiProjectEndpoint
output AZURE_OPENAI_ENDPOINT string = core.outputs.openAiEndpoint
output MODEL_DEPLOYMENT_NAME string = core.outputs.modelDeploymentName
output EMBEDDING_DEPLOYMENT_NAME string = core.outputs.embeddingDeploymentName
output COSMOS_ENDPOINT string = core.outputs.cosmosEndpoint
output COSMOS_DATABASE string = core.outputs.cosmosDatabase
output SEARCH_ENDPOINT string = core.outputs.searchEndpoint
output SEARCH_INDEX_NAME string = searchIndexName
output STORAGE_BLOB_ENDPOINT string = core.outputs.storageBlobEndpoint
output KNOWLEDGE_CONTAINER string = core.outputs.knowledgeContainer
output KNOWLEDGE_CONNECTION_NAME string = core.outputs.knowledgeConnectionName
output FOUNDRY_AGENT_PREFIX string = foundryAgentPrefix
output APPLICATIONINSIGHTS_CONNECTION_STRING string = core.outputs.appInsightsConnectionString
// This URL becomes reachable only after azd deploy creates the first real revision.
output APP_URL string = 'https://${appName}.${core.outputs.containerAppEnvironmentDefaultDomain}'

// Keep the app's managed identity distinct from AZURE_CLIENT_ID used for CI login.
output SERVICE_APP_IDENTITY_ID string = core.outputs.identityId
output SERVICE_APP_IDENTITY_CLIENT_ID string = core.outputs.identityClientId
