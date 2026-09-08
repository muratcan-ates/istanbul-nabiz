// ADLS Gen2 — the medallion lake (PLAN §4.2) and the Functions deployment container.
//
// One storage account serves both, because a second account buys nothing here and every
// account is another thing to forget to delete. Hierarchical namespace is on for the lake's
// sake: silver and gold are meant to be Delta tables (DECISIONS #6), and Delta's
// rename-based commit protocol is atomic on ADLS Gen2 and merely "eventually correct" on
// flat blob storage.
//
// UNVERIFIED RISK, and the first thing to check on a real deployment: Azure Functions is not
// on Microsoft's list of Azure services that support hierarchical namespace
// (learn.microsoft.com/azure/storage/blobs/data-lake-storage-supported-azure-services), and
// this same account is the Flex Consumption host + deployment storage. Nothing documents it
// as forbidden either, and the Functions host only needs ordinary blob/queue/table calls
// that HNS accounts serve. If the host misbehaves — no deployment package, timers that never
// fire — the fix is a second, plain StorageV2 account (isHnsEnabled false) for the function
// app, leaving this one to the lake. See docs/deploy.md §9.
//
// Keys: shared-key access is off by default. Every writer here — the collector, the MCP
// server, the developer running the collector locally — authenticates with Entra, so no
// connection string exists to leak. Turn it back on only if a tool you need cannot do
// Entra auth, and say so out loud when you do.

@description('Region for the storage account.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Days after which bronze snapshots are deleted. A volume bound, not a privacy control — see the note on the lifecycle rule below.')
@minValue(1)
@maxValue(365)
param bronzeRetentionDays int

@description('Principal object ids that get Storage Blob Data Contributor on the whole account — normally just the developer running azd, so the collector can be pointed at the real lake from a laptop.')
param dataContributorPrincipalIds array = []

@description('Set true only if some tool in the loop cannot authenticate with Entra. Leaving it false is what makes "no keys in the template" true rather than aspirational.')
param allowSharedKeyAccess bool = false

// bronze: what the collector writes today — one gzipped NDJSON file per timer tick, under
//   <source>/year=/month=/day=/hour=/, for all five sources (nabiz.collector.lake).
//   DECISIONS #6 describes bronze as the verbatim upstream body; the collector as written
//   stores parsed rows instead, which is why nothing plate-bearing reaches this account.
// silver/gold: reserved for the Delta tables of DECISIONS #6. Created now because adding a
//   container later is a change to the lake's identity; EMPTY today — the Delta writer in
//   nabiz.collector.lake only targets the local filesystem.
// deployments: the Flex Consumption package (Functions writes it with its own identity).
var bronzeContainer = 'bronze'
var lakeContainers = [
  bronzeContainer
  'silver'
  'gold'
]
var deploymentContainer = 'deployments'

var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  sku: {
    // LRS: this is recoverable public data on a student subscription. Paying for
    // geo-redundancy of a cache of open data would be a strange use of the credit.
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: allowSharedKeyAccess
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    // No soft delete: a retried timer re-uploads a blob whose name is derived from its own
    // bytes (nabiz.collector.lake.object_name), so the only blob an overwrite can replace is
    // a byte-identical one. Soft-deleted copies of that would just multiply the bill.
    deleteRetentionPolicy: {
      enabled: false
    }
    containerDeleteRetentionPolicy: {
      enabled: false
    }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for name in concat(lakeContainers, [deploymentContainer]): {
    parent: blobServices
    name: name
    properties: {
      publicAccess: 'None'
    }
  }
]

// Bounds the lake. NOT the privacy control — the İETT number plate is dropped in
// BusPosition.from_fleet_raw before any writer sees it, which is the guarantee NOTICE.md
// actually makes ("veri gölüne ... hiçbir zaman yazılmaz"). If bronze is ever switched to
// the verbatim upstream body that DECISIONS #6 describes, that promise stops being true and
// NOTICE.md has to change before the collector does.
//
// Note also what this deletes: the collector writes EVERY source under bronze/, so after
// `bronzeRetentionDays` the collected history is gone unless ADX holds a copy.
//
// Azure Functions guidance says not to run lifecycle policies on a function app's storage
// account, because they can delete blobs the host needs; the documented carve-out is to
// exclude the containers Functions owns, which are prefixed `azure-webjobs` and `scm`. The
// prefixMatch below is what keeps this rule inside `bronze/` and away from them.
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-bronze'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [
                'blockBlob'
              ]
              prefixMatch: [
                '${bronzeContainer}/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: bronzeRetentionDays
                }
              }
            }
          }
        }
      ]
    }
  }
}

// Human (or CI service principal) access to the lake. principalType is left unset so ARM
// infers it: azd may run as a user interactively and as a service principal in CI.
resource developerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for id in dataContributorPrincipalIds: {
    name: guid(storageAccount.id, id, storageBlobDataContributorRoleId)
    scope: storageAccount
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
      principalId: id
    }
  }
]

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output lakeContainerNames array = lakeContainers
// Named separately because nabiz.collector.lake reads a single container name from
// NABIZ_LAKE_CONTAINER, not a list.
output bronzeContainerName string = bronzeContainer
output deploymentContainerName string = deploymentContainer
