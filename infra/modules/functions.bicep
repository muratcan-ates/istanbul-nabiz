// The collector — Azure Functions on the Flex Consumption plan (Python 3.12, 512 MB).
//
// OPTIONAL SINCE DECISIONS #10, AND OFF BY DEFAULT (`deployCollectorFunction`). The
// collector now runs as scheduled Container Apps Jobs (modules/collectorjobs.bicep): the
// five timers below never collected the watched lines or the ETA prediction log, and the
// app was never deployable as packaged (docs/deploy.md). It stays in the template as the
// documented fallback for a region where Container Apps is refused. Do not run it next to
// the jobs: two collectors are two İETT budgets against one documented limit of 100/hour.
//
// When enabled, it is the one collector allowed to call İBB on a schedule (DECISIONS #3):
// one set of timers, roughly 6,000 executions a week. Flex Consumption is the
// right plan because it scales to zero between timer ticks and bills per GB-second, so the
// whole thing costs cents rather than the ~$13/month an always-on B1 plan would.
//
// Identity: a USER-assigned managed identity, not a system-assigned one — created in
// modules/collectoridentity.bicep and shared with the jobs, so the ADX grant written
// against its client id survives a change of host. Two reasons it is user-assigned:
//   1. Flex Consumption reads its own deployment package out of a blob container with its
//      identity. A system-assigned identity does not exist until the app is created, so the
//      role assignment it needs to read that container can only be made afterwards, and the
//      first `azd up` races Entra role propagation. A user-assigned identity exists before
//      the app, so the grants are already in place.
//   2. The ADX free cluster grant is written by hand against a client id
//      (`.add database nabiz ingestors ('aadapp=<clientId>;<tenantId>')`). A stable client
//      id that survives a redeploy of the app means that grant is written once.

@description('Region for the plan and the function app.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Name of the existing collector identity (modules/collectoridentity.bicep), which already holds Storage Blob Data Contributor on the lake.')
param collectorIdentityName string

@description('Name of the existing ADLS Gen2 account holding the lake and the deployment container.')
param storageAccountName string

@description('Container the Flex Consumption plan reads its deployment package from.')
param deploymentContainerName string

@description('Bronze container name, handed to the collector as NABIZ_LAKE_CONTAINER so the name is not hard-coded in two places.')
param bronzeContainerName string

@description('Name of the existing Application Insights component.')
param applicationInsightsName string

@description('ADX free cluster URI. Empty is valid; the collector then writes Delta only and the history tools report themselves unavailable.')
param kustoUri string = ''

@description('ADX database name.')
param kustoDatabase string = 'nabiz'

@description('NCRONTAB timer schedules (UTC) keyed ispark / iettFleet / metro / traffic / airQuality.')
param collectorSchedules object

@description('Memory per instance in MB. Flex Consumption allows 512, 2048 and 4096; 512 is the cheapest and the collector is I/O bound, not memory bound.')
@allowed([
  512
  2048
  4096
])
param instanceMemoryMB int = 512

@description('Maximum Flex Consumption instances. 40 is the platform minimum for this setting; the collector will never use more than one.')
@minValue(40)
param maximumInstanceCount int = 40

// Role definition ids are stable GUIDs; the names are here so a reviewer does not have to
// look them up.
var roles = {
  // Deployment container + host storage need Owner: the Functions host takes blob leases
  // for timer singleton locks, which Contributor alone does not always cover.
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  // (Storage Blob Data Contributor — the collector's own lake writes — is granted with the
  // identity in collectoridentity.bicep, because every host needs it.)
  // Identity-based AzureWebJobsStorage uses queues and tables for host bookkeeping.
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  monitoringMetricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
}

var storageRoleIds = [
  roles.storageBlobDataOwner
  roles.storageQueueDataContributor
  roles.storageTableDataContributor
]

resource collectorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: collectorIdentityName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

// The grants live in this module rather than in storage.bicep/monitoring.bicep because the
// identity does not exist until here. Scoping them to the account and the component keeps
// them off the resource group.
resource storageRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in storageRoleIds: {
    name: guid(storageAccount.id, collectorIdentity.id, roleId)
    scope: storageAccount
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
      principalId: collectorIdentity.properties.principalId
      // Stated explicitly: without it ARM can reject a brand-new identity that has not yet
      // replicated across Entra.
      principalType: 'ServicePrincipal'
    }
  }
]

resource metricsPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(applicationInsights.id, collectorIdentity.id, roles.monitoringMetricsPublisher)
  scope: applicationInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringMetricsPublisher)
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-collector-${resourceToken}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: 'func-nabiz-${resourceToken}'
  location: location
  // No azd-service-name tag any more: azure.yaml no longer declares a `collector` service,
  // because the default deployment has no Function for azd to find (DECISIONS #10). Code
  // reaches this app, when it is enabled, through the Functions tooling instead.
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${collectorIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: collectorIdentity.id
          }
        }
      }
      scaleAndConcurrency: {
        instanceMemoryMB: instanceMemoryMB
        maximumInstanceCount: maximumInstanceCount
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      // Flex Consumption takes the runtime from functionAppConfig.runtime; setting
      // linuxFxVersion or FUNCTIONS_EXTENSION_VERSION here is rejected.
      appSettings: [
        // Identity-based host storage: no connection string, nothing to leak.
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccount.name
        }
        {
          name: 'AzureWebJobsStorage__credential'
          value: 'managedidentity'
        }
        {
          name: 'AzureWebJobsStorage__clientId'
          value: collectorIdentity.properties.clientId
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: applicationInsights.properties.ConnectionString
        }
        // Sends telemetry with the managed identity rather than the instrumentation key —
        // this is what the Monitoring Metrics Publisher grant above is for.
        {
          name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING'
          value: 'ClientId=${collectorIdentity.properties.clientId};Authorization=AAD'
        }
        // DefaultAzureCredential inside the collector picks the right identity from this.
        {
          name: 'AZURE_CLIENT_ID'
          value: collectorIdentity.properties.clientId
        }
        // nabiz.collector.lake switches from the local data/lake directory to Azure the
        // moment AZURE_STORAGE_ACCOUNT is set, and authenticates with AZURE_CLIENT_ID above.
        // AZURE_STORAGE_CONNECTION_STRING is deliberately NOT set: that path needs a key.
        {
          name: 'AZURE_STORAGE_ACCOUNT'
          value: storageAccount.name
        }
        {
          name: 'NABIZ_LAKE_CONTAINER'
          value: bronzeContainerName
        }
        {
          name: 'NABIZ_KUSTO_URI'
          value: kustoUri
        }
        {
          name: 'NABIZ_KUSTO_DB'
          value: kustoDatabase
        }
        // nabiz.collector.kusto needs the client id explicitly: a user-assigned identity
        // cannot be inferred by DefaultAzureCredential when several could apply.
        {
          name: 'NABIZ_KUSTO_MI_CLIENT_ID'
          value: collectorIdentity.properties.clientId
        }
        // Cadences as settings rather than constants, so a gateway complaint is answered
        // with `az functionapp config appsettings set` rather than a redeploy.
        // NOTE: src/nabiz/collector/function_app.py currently hard-codes these same five
        // crons. These settings are inert until a timer_trigger reads one as
        // schedule='%NABIZ_SCHEDULE_ISPARK%'. The values here match the code exactly.
        {
          name: 'NABIZ_SCHEDULE_ISPARK'
          value: collectorSchedules.ispark
        }
        {
          name: 'NABIZ_SCHEDULE_IETT_FLEET'
          value: collectorSchedules.iettFleet
        }
        {
          name: 'NABIZ_SCHEDULE_METRO'
          value: collectorSchedules.metro
        }
        {
          name: 'NABIZ_SCHEDULE_TRAFFIC'
          value: collectorSchedules.traffic
        }
        {
          name: 'NABIZ_SCHEDULE_AIR_QUALITY'
          value: collectorSchedules.airQuality
        }
      ]
    }
  }
  // Without this the app can be created before it is allowed to read its own deployment
  // container, and the first deploy fails with a 403 that looks like a code problem.
  dependsOn: [
    storageRoleAssignments
    metricsPublisher
  ]
}

output functionAppName string = functionApp.name
output uri string = 'https://${functionApp.properties.defaultHostName}'
output principalId string = collectorIdentity.properties.principalId
output identityClientId string = collectorIdentity.properties.clientId
output identityResourceId string = collectorIdentity.id
