targetScope = 'resourceGroup'

@description('Azure region for the container app.')
param location string = resourceGroup().location

@description('Prefix applied to every resource name.')
param namePrefix string = 'gsdr'

@description('azd environment name for resource discovery.')
param environmentName string = 'grocery-disruption'

@description('Container app name supplied by the provisioning template.')
param appName string = '${namePrefix}-app-v2'

@description('Resource ID of the Container Apps managed environment.')
param containerAppEnvironmentId string

@description('Login server of the Azure Container Registry, e.g. myacr.azurecr.io.')
param acrLoginServer string

@description('Full container image reference including registry, repository and tag.')
@minLength(1)
param containerImage string

@description('Resource ID of the user-assigned managed identity.')
param identityId string

@description('Client ID of the user-assigned managed identity.')
param identityClientId string

@description('Azure AI Foundry project endpoint.')
param aiProjectEndpoint string

@description('Azure OpenAI endpoint on the Foundry account.')
param openAiEndpoint string

@description('Name of the chat model deployment.')
param modelDeploymentName string

@description('Optional faster deployment (for example gpt-4o-mini) used only for display translation. Empty reuses the chat deployment.')
param translationModelDeploymentName string = ''

@description('Name of the embedding model deployment.')
param embeddingDeploymentName string

@description('Cosmos DB document endpoint.')
param cosmosEndpoint string

@description('Cosmos DB SQL database name.')
param cosmosDatabase string = 'GroceryDisruptionDB'

@description('Azure AI Search endpoint.')
param searchEndpoint string

@description('Azure AI Search index name.')
param searchIndexName string = 'grocery-disruption-knowledge'

param knowledgeContainer string = 'grocery-knowledge'
param knowledgeConnectionName string = 'knowledge-search'
param foundryAgentPrefix string = 'gsdr'

@description('Primary blob endpoint of the storage account.')
param storageBlobEndpoint string

@description('Application Insights connection string.')
param appInsightsConnectionString string

var serviceEnvironment = [
  {
    name: 'AZURE_CLIENT_ID'
    value: identityClientId
  }
  {
    name: 'AZURE_TOKEN_CREDENTIALS'
    value: 'ManagedIdentityCredential'
  }
  {
    name: 'AZURE_AI_PROJECT_ENDPOINT'
    value: aiProjectEndpoint
  }
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: openAiEndpoint
  }
  {
    name: 'MODEL_DEPLOYMENT_NAME'
    value: modelDeploymentName
  }
  {
    name: 'MODEL_MAX_CONCURRENCY'
    value: '6'
  }
  {
    name: 'TRANSLATION_MODEL_DEPLOYMENT_NAME'
    value: translationModelDeploymentName
  }
  {
    name: 'TRANSLATION_MAX_CONCURRENCY'
    value: '4'
  }
  {
    name: 'EMBEDDING_DEPLOYMENT_NAME'
    value: embeddingDeploymentName
  }
  {
    name: 'COSMOS_ENDPOINT'
    value: cosmosEndpoint
  }
  {
    name: 'COSMOS_DATABASE'
    value: cosmosDatabase
  }
  {
    name: 'SEARCH_ENDPOINT'
    value: searchEndpoint
  }
  {
    name: 'SEARCH_INDEX_NAME'
    value: searchIndexName
  }
  {
    name: 'STORAGE_BLOB_ENDPOINT'
    value: storageBlobEndpoint
  }
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: appInsightsConnectionString
  }
  {
    name: 'SELF_BASE_URL'
    value: 'http://127.0.0.1:8000'
  }
  {
    name: 'ENABLE_DELIBERATION'
    value: 'true'
  }
  {
    name: 'ENABLE_FOUNDRY_HOSTED_AGENTS'
    value: 'true'
  }
  {
    name: 'KNOWLEDGE_CONTAINER'
    value: knowledgeContainer
  }
  {
    name: 'KNOWLEDGE_CONNECTION_NAME'
    value: knowledgeConnectionName
  }
  {
    name: 'FOUNDRY_AGENT_PREFIX'
    value: foundryAgentPrefix
  }
]

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: {
    'azd-env-name': environmentName
    'azd-service-name': 'app'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnvironmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'app'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/api/health'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 60
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/health'
                port: 8000
                scheme: 'HTTP'
              }
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/health'
                port: 8000
                scheme: 'HTTP'
              }
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
          env: serviceEnvironment
        }
      ]
      scale: {
        minReplicas: 1
        // SSE streams, workflow state and approval gates are process-local.
        maxReplicas: 1
      }
    }
  }
}

resource seedJob 'Microsoft.App/jobs@2024-03-01' = {
  name: '${appName}-seed'
  location: location
  tags: {
    'azd-env-name': environmentName
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: containerAppEnvironmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: {
        replicaCompletionCount: 1
        parallelism: 1
      }
      registries: [
        {
          server: acrLoginServer
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'seed'
          image: containerImage
          command: [
            'python'
            '-m'
            'scripts.run_seed_job'
          ]
          env: serviceEnvironment
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
    }
  }
}

output appUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output appName string = containerApp.name
output APP_URL string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output AZURE_CONTAINER_APP_NAME string = containerApp.name
output AZURE_SEED_JOB_NAME string = seedJob.name
