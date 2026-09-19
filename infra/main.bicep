targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Prefix applied to every resource name.')
param namePrefix string = 'gsdr'

@description('Name of the chat model deployment.')
param modelDeploymentName string = 'gpt-4o'

@description('Capacity (TPM in thousands) for the chat model deployment.')
param modelCapacity int = 100

@description('Name of the embedding model deployment.')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Capacity (TPM in thousands) for the embedding model deployment.')
param embeddingCapacity int = 50

@description('Name of the project connection that exposes the knowledge index to hosted agents.')
param knowledgeConnectionName string = 'knowledge-search'

var suffix = uniqueString(resourceGroup().id)

var cosmosContainers = [
  { name: 'products', partitionKey: '/partitionKey' }
  { name: 'suppliers', partitionKey: '/partitionKey' }
  { name: 'warehouses', partitionKey: '/partitionKey' }
  { name: 'stores', partitionKey: '/partitionKey' }
  { name: 'inventory', partitionKey: '/partitionKey' }
  { name: 'demandForecast', partitionKey: '/partitionKey' }
  { name: 'substitutes', partitionKey: '/partitionKey' }
  { name: 'commitments', partitionKey: '/partitionKey' }
  { name: 'promotions', partitionKey: '/partitionKey' }
  { name: 'replenishmentSchedule', partitionKey: '/partitionKey' }
  { name: 'pastDisruptions', partitionKey: '/partitionKey' }
  { name: 'playbooks', partitionKey: '/partitionKey' }
  { name: 'stakeholders', partitionKey: '/partitionKey' }
  { name: 'signals', partitionKey: '/partitionKey' }
]

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var azureAiDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchIndexDataReaderRoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-identity-${suffix}'
  location: location
}

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs-${suffix}'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-appi-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${namePrefix}st${suffix}'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource wikiContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'grocery-knowledge'
  properties: {
    publicAccess: 'None'
  }
}

// ---------------------------------------------------------------------------
// Azure AI Search
// ---------------------------------------------------------------------------

resource search 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: '${namePrefix}-search-${suffix}'
  location: location
  sku: {
    name: 'basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    partitionCount: 1
    replicaCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    semanticSearch: 'free'
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB
// ---------------------------------------------------------------------------

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${namePrefix}-cosmos-${suffix}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableFreeTier: false
    capabilities: []
    publicNetworkAccess: 'Enabled'
    networkAclBypass: 'AzureServices'
    isVirtualNetworkFilterEnabled: false
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
  }
}

// Shared database-level throughput keeps the demo containers under per-container minimums.
resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'GroceryDisruptionDB'
  properties: {
    resource: {
      id: 'GroceryDisruptionDB'
    }
    options: {
      throughput: 400
    }
  }
}

resource cosmosContainerResources 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = [
  for container in cosmosContainers: {
    parent: cosmosDatabase
    name: container.name
    properties: {
      resource: {
        id: container.name
        partitionKey: {
          paths: [
            container.partitionKey
          ]
          kind: 'Hash'
        }
      }
    }
  }
]

// ---------------------------------------------------------------------------
// Azure AI Foundry
// ---------------------------------------------------------------------------

resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: '${namePrefix}-foundry-${suffix}'
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: '${namePrefix}-foundry-${suffix}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: foundry
  name: '${namePrefix}-project'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Grocery Supply Disruption Response'
    description: 'Multi-agent grocery disruption response workspace.'
  }
}

// Lets hosted agents ground answers on the knowledge index without handling keys.
resource knowledgeSearchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: foundryProject
  name: knowledgeConnectionName
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${search.name}.search.windows.net'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
      location: location
    }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: foundry
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
  }
}

// Model deployments on one account must be serialized; parallel creation fails.
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: foundry
  name: embeddingDeploymentName
  sku: {
    name: 'Standard'
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
      version: '1'
    }
  }
  dependsOn: [
    chatDeployment
  ]
}

// ---------------------------------------------------------------------------
// Container platform
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${namePrefix}acr${suffix}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env-${suffix}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Role assignments
// ---------------------------------------------------------------------------

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, identity.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource azureAiDeveloperAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, azureAiDeveloperRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiDeveloperRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource openAiUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, cognitiveServicesOpenAiUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      cognitiveServicesOpenAiUserRoleId
    )
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cognitiveServicesUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, cognitiveServicesUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchIndexDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, searchIndexDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      searchIndexDataContributorRoleId
    )
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource searchServiceContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, searchServiceContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The project identity (not the app identity) performs retrieval for the agent knowledge tool.
resource projectSearchIndexReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, foundryProject.id, searchIndexDataReaderRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReaderRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectSearchServiceContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, foundryProject.id, searchServiceContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageBlobDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, storageBlobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataContributorRoleId
    )
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosDataContributorAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, '00000000-0000-0000-0000-000000000002')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: identity.properties.principalId
    scope: cosmos.id
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

output identityId string = identity.id
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output containerAppEnvironmentId string = containerAppEnvironment.id
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosAccountName string = cosmos.name
output foundryAccountName string = foundry.name
output foundryEndpoint string = foundry.properties.endpoint
output aiProjectEndpoint string = 'https://${foundry.name}.services.ai.azure.com/api/projects/${namePrefix}-project'
output knowledgeConnectionName string = knowledgeSearchConnection.name
output openAiEndpoint string = 'https://${foundry.name}.openai.azure.com/'
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchServiceName string = search.name
output storageAccountName string = storage.name
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output logAnalyticsWorkspaceId string = logAnalytics.id
output modelDeploymentName string = chatDeployment.name
output embeddingDeploymentName string = embeddingDeployment.name
