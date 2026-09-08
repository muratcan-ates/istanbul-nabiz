// Container Apps — hosts `ibb-mcp` over streamable HTTP (and, later, the Nabız web UI).
//
// Why Container Apps and not App Service: minReplicas 0 plus the monthly free grant
// (180,000 vCPU-seconds, 360,000 GiB-seconds, 2,000,000 requests) means a server that is
// idle most of the week costs nothing, and a demo that gets hammered for ten minutes still
// costs nothing. An App Service B1 would be ~$13/month of a ~$100 credit, forever.
//
// maxReplicas defaults to ONE, and that is a correctness setting rather than a cost one.
// The İETT hourly budget (PoliteClient: 80 requests against İETT's documented 100) and the
// 6 s per-host gate for api.ibb.gov.tr both live in process (DECISIONS #3). Two replicas
// are therefore two independent budgets: up to 160 İETT requests an hour, and a gateway
// that the project promises to call at most every 6 seconds getting hit every 3 — which is
// exactly the pattern that 503s after ~15 rapid calls. Users would also see two different
// "how old is this data" answers, because the TTL cache is per process too. Scaling out
// needs a shared cache and a shared budget first; neither is in scope for this sprint.
//
// COST WARNING — the container registry:
//   azd's remote build (no local Docker needed) pushes to an Azure Container Registry.
//   Basic is ~$0.167/day, about $1.17/week — the single largest line item in this template.
//   Two ways out, both supported here:
//     1. Do not deploy this at all: `azd env set DEPLOY_CONTAINER_APP false`. The MCP server
//        still runs locally over stdio for VS Code Copilot / Claude, which is how the
//        server is used in most of the demo anyway.
//     2. Keep the Container App but drop the registry:
//        `azd env set DEPLOY_CONTAINER_REGISTRY false` and
//        `azd env set MCP_CONTAINER_IMAGE ghcr.io/<you>/ibb-mcp:<tag>` with a public image.
//        azd can no longer build for you; you push the image yourself.

@description('Region for the environment and the app.')
param location string

@description('Tags applied to every resource. azd-service-name is added on the app itself.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Resource id of the Log Analytics workspace that receives console and system logs.')
param logAnalyticsWorkspaceId string

@description('Application Insights connection string, passed to the server for OpenTelemetry export.')
param applicationInsightsConnectionString string

@description('Name of the existing Application Insights component, so the app identity can be granted Monitoring Metrics Publisher on it.')
param applicationInsightsName string

@description('Name of the existing storage account. The server reads reference and gold data; it never writes.')
param storageAccountName string

@description('ADX free cluster URI. Empty is valid — history-backed tools then report available:false.')
param kustoUri string = ''

@description('ADX database name.')
param kustoDatabase string = 'nabiz'

@description('Replica ceiling. Keep at 1: the rate-limit budget and the cache are per process.')
@minValue(1)
@maxValue(10)
param maxReplicas int = 1

@description('Create an Azure Container Registry for azd remote build. False means you supply containerImage from a registry that allows anonymous pull.')
param createRegistry bool = true

@description('Image to run. Empty uses a public placeholder so the very first deployment succeeds before any image exists; azd replaces it on `azd deploy`.')
param containerImage string = ''

// A container that merely listens on the wrong port still counts as a healthy revision, so
// the placeholder does not fail the deployment — it just returns 502 until azd pushes the
// real image.
var placeholderImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var effectiveImage = empty(containerImage) ? placeholderImage : containerImage

// `ibb-mcp --transport http --host 0.0.0.0 --port 8000`
var containerPort = 8000

var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  // Read-only on purpose: the collector writes the lake, the server only reads it.
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  monitoringMetricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
}

// User-assigned again, for the same reason as the collector: the AcrPull grant has to exist
// before the app first pulls, and a system-assigned identity does not exist that early.
resource mcpIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mcp-${resourceToken}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = if (createRegistry) {
  name: 'cr${resourceToken}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    // No admin user: pulls are authorised by the managed identity below, so there is no
    // registry password anywhere in this template or in the azd environment file.
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createRegistry) {
  name: guid(resourceGroup().id, 'acr', mcpIdentity.id, roles.acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: mcpIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

resource lakeReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, mcpIdentity.id, roles.storageBlobDataReader)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
    principalId: mcpIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource metricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(applicationInsights.id, mcpIdentity.id, roles.monitoringMetricsPublisher)
  scope: applicationInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringMetricsPublisher)
    principalId: mcpIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${resourceToken}'
  location: location
  tags: tags
  properties: {
    // 'azure-monitor' instead of 'log-analytics': the log-analytics destination wants the
    // workspace shared key, which would put a secret in the template. The diagnostic
    // setting below routes the same logs to the same workspace with no key at all.
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    zoneRedundant: false
  }
  // No workloadProfiles block: that keeps this a Consumption-only environment, which is the
  // one the monthly free grant applies to. Adding a Dedicated profile bills per hour.
}

resource environmentDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-log-analytics'
  scope: containerEnv
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-mcp-${resourceToken}'
  location: location
  // azd matches this tag to the `mcp` service in azure.yaml.
  tags: union(tags, { 'azd-service-name': 'mcp' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${mcpIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        // Public: the whole point is that any MCP client can reach it. The data is public
        // İBB data; the throttling that protects the upstream is in the server, not here.
        external: true
        targetPort: containerPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: createRegistry
        ? [
            {
              server: registry.properties.loginServer
              identity: mcpIdentity.id
            }
          ]
        : []
    }
    template: {
      containers: [
        {
          name: 'ibb-mcp'
          image: effectiveImage
          resources: {
            // json() because Bicep has no float literal. 0.5 vCPU / 1 GiB is a valid
            // Consumption combination and is roughly 3x what the server needs.
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: mcpIdentity.properties.clientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsightsConnectionString
            }
            {
              name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
              value: 'ClientId=${mcpIdentity.properties.clientId};Authorization=AAD'
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT'
              value: storageAccount.name
            }
            {
              name: 'NABIZ_KUSTO_URI'
              value: kustoUri
            }
            {
              name: 'NABIZ_KUSTO_DB'
              value: kustoDatabase
            }
            {
              name: 'NABIZ_KUSTO_MI_CLIENT_ID'
              value: mcpIdentity.properties.clientId
            }
            {
              // GTFS reference data is baked into the image; see the Dockerfile in
              // docs/deploy.md.
              name: 'NABIZ_GTFS_DIR'
              value: '/app/data/reference/gtfs'
            }
            {
              name: 'NABIZ_PLACES_CSV'
              value: '/app/data/reference/places.csv'
            }
          ]
        }
      ]
      scale: {
        // Zero when nobody is asking. A cold start costs the first caller a few seconds and
        // costs the credit nothing for the other 167 hours of the week.
        minReplicas: 0
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    acrPull
  ]
}

output containerAppName string = containerApp.name
output uri string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output environmentName string = containerEnv.name
output environmentId string = containerEnv.id
output principalId string = mcpIdentity.properties.principalId
output identityClientId string = mcpIdentity.properties.clientId
output registryName string = createRegistry ? registry.name : ''
output registryLoginServer string = createRegistry ? registry.properties.loginServer : ''
