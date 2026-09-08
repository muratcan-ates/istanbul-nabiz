// Azure Maps Gen2 (G2) — the map behind the web UI: car parks, buses on a line, metro
// stations, air-quality station colours.
//
// Off by default (deployMaps=false in main.bicep) for one reason: on an Azure for Students
// subscription the hidden "Allowed resource deployment regions" policy frequently refuses
// Microsoft.Maps, and a refusal here would fail the deployment of everything else. The web
// UI's fallback is MapLibre GL + OpenStreetMap tiles, which needs no Azure resource at all
// (PLAN §15).
//
// Gen2 (G2) rather than Gen1 (S0/S1): Gen2 bills per transaction with a monthly free tier
// that comfortably covers map tiles for a demo, and Gen1 is on a retirement path.
//
// Location is 'global' — Azure Maps has no regional deployment, which is also why the
// region policy either allows the resource provider or does not.

@description('Tags applied to every resource.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Principal object ids granted Azure Maps Data Reader — the Container App identity (the MCP server today, the web UI when it lands), so the browser gets a short-lived Entra token minted server-side instead of an embedded subscription key.')
param dataReaderPrincipalIds array = []

@description('Turn off Azure Maps subscription keys entirely. Left FALSE because src/nabiz/web/main.py reads NABIZ_MAPS_KEY today; flipping it to true breaks that page until the web layer mints Entra tokens server-side with the Data Reader grant below. Either way, no key is ever emitted by this template — a key path means someone fetches it deliberately with `az maps account keys list`.')
param disableLocalAuth bool = false

var azureMapsDataReaderRoleId = '423170ca-a8f6-4b0f-8487-9e4eb8f49bfa'

resource mapsAccount 'Microsoft.Maps/accounts@2023-06-01' = {
  name: 'map-nabiz-${resourceToken}'
  location: 'global'
  tags: tags
  sku: {
    name: 'G2'
  }
  kind: 'Gen2'
  properties: {
    // A subscription key in a public web page is a key anybody can copy and spend the
    // credit with; the SDK's Entra path (authType 'anonymous' plus a token endpoint on the
    // web app, backed by the Data Reader grant below) has no such failure mode. Preferred,
    // but not the default — see the parameter description.
    disableLocalAuth: disableLocalAuth
  }
}

resource dataReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for id in dataReaderPrincipalIds: {
    name: guid(mapsAccount.id, id, azureMapsDataReaderRoleId)
    scope: mapsAccount
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureMapsDataReaderRoleId)
      principalId: id
      principalType: 'ServicePrincipal'
    }
  }
]

output mapsAccountName string = mapsAccount.name
output mapsAccountId string = mapsAccount.id
// The Web SDK needs this as `clientId` when authenticating with Entra.
output mapsClientId string = mapsAccount.properties.uniqueId
