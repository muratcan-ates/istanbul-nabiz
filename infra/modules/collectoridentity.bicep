// The collector's identity — one user-assigned managed identity, whichever host runs it.
//
// It used to live inside modules/functions.bicep, which was fine while the Function was
// the only collector. Since DECISIONS #10 the collector runs as Container Apps Jobs and the
// Function is optional and off by default, so the identity moved here, created
// unconditionally. That keeps one property worth more than the move costs: the Azure Data
// Explorer free cluster admits the collector by CLIENT ID, in a command typed by hand once
// (`.add database nabiz ingestors ('aadapp=<clientId>;<tenantId>')`). With one identity for
// both hosts, switching host — or re-provisioning either — never invalidates that grant.
//
// The name `id-collector-<token>` and the role assignment name below are exactly what
// functions.bicep used, so a deployment made before the move converges onto the same
// resources instead of orphaning them.
//
// Only the grant every host needs is made here: writing the lake. Host-specific grants
// stay with the host — the Functions host storage roles in functions.bicep, AcrPull in
// containerapps.bicep.

@description('Region for the identity.')
param location string

@description('Tags applied to every resource.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Name of the existing storage account holding the lake.')
param storageAccountName string

// Storage Blob Data Contributor: the least privilege the collector's own lake writes need
// (nabiz.collector.lake uploads with DefaultAzureCredential; no key exists to use instead).
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource collectorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-collector-${resourceToken}'
  location: location
  tags: tags
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource lakeWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, collectorIdentity.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: collectorIdentity.properties.principalId
    // Stated explicitly: without it ARM can reject a brand-new identity that has not yet
    // replicated across Entra.
    principalType: 'ServicePrincipal'
  }
}

output name string = collectorIdentity.name
output resourceId string = collectorIdentity.id
output clientId string = collectorIdentity.properties.clientId
output principalId string = collectorIdentity.properties.principalId
