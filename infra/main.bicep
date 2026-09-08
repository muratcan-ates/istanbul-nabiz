// İstanbul Nabız — the whole Azure footprint, deployed by `azd up`.
//
// Scope is the SUBSCRIPTION, not a resource group: `azd up` should work against a fresh
// Azure for Students subscription where no resource group exists yet, and tearing the
// project down should be one `azd down` that removes the group with it.
//
// What is deliberately NOT here, and why (Azure for Students has ~$100 of credit, and when
// the credit runs out the whole subscription is disabled — a dead subscription costs more
// than a missing feature):
//
//   * Azure AI Search  — Basic is ~$2.42/day even completely idle. That is the entire
//                        credit in six weeks for a service this project does not need:
//                        every tool is parametric, there is no retrieval layer (DECISIONS #2).
//   * Stream Analytics — no free tier at all; the collector Function does the same job.
//   * Data Factory     — data flows bill per vCore-hour; the collector is a timer.
//   * Marketplace      — anything from Marketplace bills outside the credit and can charge
//                        a card directly.
//   * Azure Data Explorer — the free cluster (DECISIONS #1) is created OUTSIDE ARM at
//                        https://dataexplorer.azure.com/freecluster with a Microsoft
//                        account. It has no ARM resource provider, so it cannot be
//                        expressed here at all. Its URI arrives as a parameter and is
//                        handed to the services as an app setting; empty is a valid state,
//                        and the history-backed tools then report `available: false`.
//
// Region policy: Azure for Students carries a hidden "Allowed resource deployment regions"
// policy assignment (typically ~5 regions, and the list differs per subscription). Pick
// `location` from the intersection of that policy and the Functions Flex Consumption region
// list — docs/deploy.md walks through the two commands that produce it.

targetScope = 'subscription'

// ---------------------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------------------

@minLength(1)
@maxLength(24)
@description('Name of the azd environment. Becomes the resource group name and the azd-env-name tag.')
param environmentName string

@minLength(1)
@description('Region for every regional resource. MUST be allowed by the subscription region policy AND support Functions Flex Consumption — see docs/deploy.md.')
param location string

@description('Override the generated resource group name. Empty means rg-<environmentName>.')
param resourceGroupName string = ''

@description('Object id of the human or service principal running the deployment. azd supplies AZURE_PRINCIPAL_ID. Gets read/write access to the lake so the collector can be run locally against real containers. Empty disables that grant.')
param principalId string = ''

@description('Deploy the Container App that hosts the MCP server. Creates an Azure Container Registry (Basic) as a side effect — see the note in modules/containerapps.bicep.')
param deployContainerApp bool = true

@description('Create an Azure Container Registry so azd can build the MCP image remotely (no local Docker). Basic is ~$1.17/week — the largest single line item in this template. Set false and supply mcpContainerImage from a public registry to avoid it.')
param deployContainerRegistry bool = true

@description('Pin the MCP server image instead of letting azd build one. Required when deployContainerRegistry is false. Empty means a public placeholder image runs until `azd deploy` pushes the real one.')
param mcpContainerImage string = ''

@description('Deploy an Azure Maps Gen2 (G2) account for the web map. Defaults to false: the region policy on a student subscription frequently refuses Microsoft.Maps, and a refusal must not fail the deployment of everything else. The web UI falls back to MapLibre + OpenStreetMap.')
param deployMaps bool = false

@description('URI of the Azure Data Explorer free cluster, e.g. https://<name>.<region>.kusto.windows.net. Created outside ARM. Empty is valid — history-backed tools then report themselves unavailable rather than guessing.')
param kustoUri string = ''

@description('Database inside the ADX free cluster.')
param kustoDatabase string = 'nabiz'

@description('Days to keep bronze snapshots. This is a volume and cost bound, NOT a privacy control: the collector writes parsed rows (nabiz.collector.snapshots), and the İETT number plate is already gone by then — dropped in BusPosition.from_fleet_raw, per DECISIONS #7 and the promise in NOTICE.md that it never reaches the lake. Note that every source lands under bronze/, so this is also the age at which collected history disappears when there is no ADX cluster to hold it.')
@minValue(1)
@maxValue(365)
param bronzeRetentionDays int = 30

@description('Ceiling on MCP server replicas. ONE on purpose: the İETT hourly budget (80 of the documented 100) and the 6 s per-host gate live in process, so N replicas make N independent budgets — two replicas would ask İETT for up to 160 requests an hour and hit api.ibb.gov.tr every 3 s (DECISIONS #3, NOTICE.md). Raising this needs a shared cache and a shared budget first.')
@minValue(1)
@maxValue(10)
param mcpMaxReplicas int = 1

@description('Daily Log Analytics ingestion cap in GB, as a string because Bicep has no float literal. 0.5 GB/day keeps a runaway trace loop from eating the credit; the free grant is 5 GB/month.')
param dailyLogCapGb string = '0.5'

@description('Collector timer schedules (NCRONTAB, UTC). Overridable without a code change so the cadence can be slowed if the İBB gateway complains.')
param collectorSchedules object = {
  ispark: '0 */10 * * * *'
  iettFleet: '0 */2 * * * *'
  metro: '0 5 * * * *'
  traffic: '0 10 * * * *'
  airQuality: '0 15 * * * *'
}

// ---------------------------------------------------------------------------------------
// Naming
// ---------------------------------------------------------------------------------------

// One token per (subscription, environment, region) keeps globally-unique names stable
// across redeploys — a changed storage account name would orphan the whole lake.
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

var tags = {
  'azd-env-name': environmentName
  project: 'istanbul-nabiz'
  // Attribution travels with the infrastructure too, not only the README (NOTICE.md).
  dataSource: 'ibb-open-data-portal'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : 'rg-${environmentName}'
  location: location
  tags: tags
}

// ---------------------------------------------------------------------------------------
// Modules
// ---------------------------------------------------------------------------------------

// Monitoring first: both compute services want the Application Insights connection string,
// and the Container Apps environment ships its console logs to the same workspace.
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    dailyLogCapGb: dailyLogCapGb
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    bronzeRetentionDays: bronzeRetentionDays
    // The deploying developer, so `python -m nabiz.collector` can be pointed at the real
    // lake from the laptop without a connection string existing anywhere.
    dataContributorPrincipalIds: empty(principalId) ? [] : [principalId]
  }
}

module functions 'modules/functions.bicep' = {
  name: 'functions'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    storageAccountName: storage.outputs.storageAccountName
    deploymentContainerName: storage.outputs.deploymentContainerName
    bronzeContainerName: storage.outputs.bronzeContainerName
    applicationInsightsName: monitoring.outputs.applicationInsightsName
    kustoUri: kustoUri
    kustoDatabase: kustoDatabase
    collectorSchedules: collectorSchedules
  }
}

module containerapps 'modules/containerapps.bicep' = if (deployContainerApp) {
  name: 'containerapps'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    applicationInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
    applicationInsightsName: monitoring.outputs.applicationInsightsName
    storageAccountName: storage.outputs.storageAccountName
    kustoUri: kustoUri
    kustoDatabase: kustoDatabase
    maxReplicas: mcpMaxReplicas
    createRegistry: deployContainerRegistry
    containerImage: mcpContainerImage
  }
}

module maps 'modules/maps.bicep' = if (deployMaps) {
  name: 'maps'
  scope: rg
  params: {
    tags: tags
    resourceToken: resourceToken
    // Grants the Container App identity Azure Maps Data Reader, so the web layer can mint
    // short-lived browser tokens instead of shipping a subscription key. Subscription keys
    // stay enabled by default because src/nabiz/web/main.py still reads NABIZ_MAPS_KEY;
    // pass disableLocalAuth to this module once that page is on Entra.
    dataReaderPrincipalIds: deployContainerApp ? [containerapps.outputs.principalId] : []
  }
}

// ---------------------------------------------------------------------------------------
// Outputs — everything azd writes into .azure/<env>/.env
// ---------------------------------------------------------------------------------------

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name

// azd needs the registry endpoint to push the remotely-built MCP image.
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = (deployContainerApp && deployContainerRegistry) ? containerapps.outputs.registryLoginServer : ''
output AZURE_CONTAINER_REGISTRY_NAME string = (deployContainerApp && deployContainerRegistry) ? containerapps.outputs.registryName : ''
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = deployContainerApp ? containerapps.outputs.environmentName : ''

output SERVICE_MCP_NAME string = deployContainerApp ? containerapps.outputs.containerAppName : ''
output SERVICE_MCP_URI string = deployContainerApp ? containerapps.outputs.uri : ''
output SERVICE_COLLECTOR_NAME string = functions.outputs.functionAppName
output SERVICE_COLLECTOR_URI string = functions.outputs.uri

output NABIZ_STORAGE_ACCOUNT string = storage.outputs.storageAccountName
output NABIZ_LAKE_URL string = storage.outputs.blobEndpoint
output NABIZ_KUSTO_URI string = kustoUri
output NABIZ_KUSTO_DB string = kustoDatabase

// The Function's identity, needed verbatim for the ADX grant:
//   .add database <db> ingestors ('aadapp=<clientId>;<tenantId>')
output NABIZ_COLLECTOR_CLIENT_ID string = functions.outputs.identityClientId
output NABIZ_COLLECTOR_PRINCIPAL_ID string = functions.outputs.principalId

output NABIZ_MAPS_CLIENT_ID string = deployMaps ? maps.outputs.mapsClientId : ''
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.applicationInsightsName
