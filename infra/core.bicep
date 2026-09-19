targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Prefix applied to every resource name.')
param namePrefix string = 'gsdr'

@description('Tags applied to the provisioned resources.')
param tags object = {}

@description('Object ID of the user or service principal running seed and agent provisioning.')
param principalId string = ''

@description('Name of the chat model deployment.')
param modelDeploymentName string = 'gpt-4o'

@description('Chat model published in the Azure OpenAI catalog.')
param modelName string = 'gpt-4o'

@description('Chat model version available in the selected region.')
param modelVersion string = '2024-11-20'

@description('Chat model deployment SKU.')
param modelSku string = 'GlobalStandard'

@minValue(1)
@description('Capacity (TPM in thousands) for the chat model deployment.')
param modelCapacity int = 100

@description('Name of the embedding model deployment.')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Embedding model published in the Azure OpenAI catalog.')
param embeddingModelName string = 'text-embedding-3-large'

@description('Embedding model version available in the selected region.')
param embeddingModelVersion string = '1'

@description('Embedding model deployment SKU.')
param embeddingSku string = 'Standard'

@minValue(1)
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
// Azure AI User (renamed Foundry User) supports the project's versioned agents API.
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
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
  tags: tags
}

// ---------------------------------------------------------------------------
// Observability
// ---------------------------------------------------------------------------

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs-${suffix}'
  location: location
  tags: tags
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
  tags: tags
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
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
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
  tags: tags
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
    disableLocalAuth: true
    semanticSearch: 'free'
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB
// ---------------------------------------------------------------------------

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${namePrefix}-cosmos-${suffix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    disableLocalAuth: true
    enableFreeTier: false
    capabilities: []
    publicNetworkAccess: 'Disabled'
    networkAclBypass: 'None'
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
  tags: tags
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
    disableLocalAuth: true
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: foundry
  name: '${namePrefix}-project'
  location: location
  tags: tags
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
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// Model deployments on one account must be serialized; parallel creation fails.
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: foundry
  name: embeddingDeploymentName
  sku: {
    name: embeddingSku
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
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
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet-${suffix}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'container-apps'
        properties: {
          addressPrefix: '10.42.0.0/23'
          delegations: [
            {
              name: 'container-apps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: '10.42.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'container-apps-v2'
        properties: {
          addressPrefix: '10.42.4.0/23'
          delegations: [
            {
              name: 'container-apps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
    ]
  }
}

resource cosmosPrivateDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.documents.azure.com'
  location: 'global'
  tags: tags
}

resource cosmosDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: cosmosPrivateDns
  name: '${namePrefix}-cosmos-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${namePrefix}-cosmos-pe-${suffix}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: virtualNetwork.properties.subnets[1].id
    }
    privateLinkServiceConnections: [
      {
        name: 'cosmos-sql'
        properties: {
          privateLinkServiceId: cosmos.id
          groupIds: [
            'Sql'
          ]
        }
      }
    ]
  }
}

resource cosmosPrivateDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: cosmosPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'cosmos-sql'
        properties: {
          privateDnsZoneId: cosmosPrivateDns.id
        }
      }
    ]
  }
}

resource blobPrivateDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}

resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: blobPrivateDns
  name: '${namePrefix}-blob-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource blobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${namePrefix}-blob-pe-${suffix}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: virtualNetwork.properties.subnets[1].id
    }
    privateLinkServiceConnections: [
      {
        name: 'storage-blob'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource blobPrivateDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'storage-blob'
        properties: {
          privateDnsZoneId: blobPrivateDns.id
        }
      }
    ]
  }
}

// Preserve prior environments and their subnet during non-destructive recovery.
resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env-private-v2-${suffix}'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: virtualNetwork.properties.subnets[2].id
      internal: false
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
  dependsOn: [
    cosmosDnsLink
    cosmosPrivateDnsGroup
    blobDnsLink
    blobPrivateDnsGroup
  ]
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

resource runtimeFoundryUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundryProject
  name: guid(foundryProject.id, identity.id, foundryUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
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

// Do not set principalType: azd supports both an interactive user and a CI service principal.
resource deployerFoundryUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: foundryProject
  name: guid(foundryProject.id, principalId, foundryUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
    principalId: principalId
  }
}

resource deployerOpenAiUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: foundry
  name: guid(foundry.id, principalId, cognitiveServicesOpenAiUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
    principalId: principalId
  }
}

resource deployerSearchAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in [searchServiceContributorRoleId, searchIndexDataContributorRoleId]: if (!empty(principalId)) {
    scope: search
    name: guid(search.id, principalId, roleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
      principalId: principalId
    }
  }
]

resource deployerStorageAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: storage
  name: guid(storage.id, principalId, storageBlobDataContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: principalId
  }
}

resource deployerCosmosAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = if (!empty(principalId)) {
  parent: cosmos
  name: guid(cosmos.id, principalId, '00000000-0000-0000-0000-000000000002')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: principalId
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
output containerAppEnvironmentDefaultDomain string = containerAppEnvironment.properties.defaultDomain
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosDatabase string = cosmosDatabase.name
output knowledgeContainer string = wikiContainer.name
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
