// Log Analytics + Application Insights.
//
// This is the layer that turns "the agent called a tool" into something a reviewer can see:
// an end-to-end trace of agent -> MCP tool -> upstream İBB call -> model (PLAN §6). Both
// compute services write to the same workspace so one query spans them.
//
// Cost: the Azure Monitor free grant is 5 GB/month across the workspace. A tracing bug that
// logs every fleet position (6,900 vehicles every 2 minutes) would blow through that in a
// day, so the workspace carries a hard daily cap. Hitting the cap stops ingestion until the
// next UTC day; losing telemetry is recoverable, losing the subscription's credit is not.

@description('Region for the workspace and the Application Insights component.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Daily ingestion cap in GB. A string because Bicep has no float literal; converted with json().')
param dailyLogCapGb string

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    // 30 days is the free retention period; anything longer bills per GB-month.
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: json(dailyLogCapGb)
    }
    features: {
      // Workspace-based Application Insights needs this off to allow the component to
      // write into the workspace with its own permissions.
      disableLocalAuth: false
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    // Workspace-based: classic Application Insights was retired, and the workspace is
    // where the daily cap above actually applies.
    WorkspaceResourceId: logAnalytics.id
    // Left enabled deliberately. The collector authenticates to this component with its
    // managed identity (Monitoring Metrics Publisher + APPLICATIONINSIGHTS_AUTHENTICATION_STRING),
    // but the Container Apps environment and any SDK not yet wired for Entra would silently
    // stop reporting if local auth were disabled. Flip to true once every writer is on Entra.
    DisableLocalAuth: false
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output logAnalyticsWorkspaceId string = logAnalytics.id
output logAnalyticsWorkspaceName string = logAnalytics.name
output applicationInsightsName string = applicationInsights.name
output applicationInsightsId string = applicationInsights.id
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString
