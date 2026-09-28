// Citizen and simulated-operator web app. The parent enables this only after an image exists.
// One replica is a correctness limit: SQLite and the in-process upstream budget do not scale out.
@description('Azure region of the existing Container Apps environment.')
param location string
@description('Tags shared with the parent deployment.')
param tags object
@description('Stable name suffix from main.bicep.')
param resourceToken string
@description('Name of the existing Container Apps environment.')
param environmentName string
@minLength(1)
@description('Reviewed web image reference, preferably an immutable digest. No placeholder is used.')
param containerImage string
@description('Existing private ACR name; empty for a publicly pullable image.')
param registryName string = ''
@description('Existing private ACR login server; empty for a publicly pullable image.')
param registryLoginServer string = ''
@description('Use recorded fixtures by default; false requires approval for live upstream calls.')
param offlineMode bool = true

@minValue(1)
@maxValue(1)
@description('One until SQLite locking and the per-process upstream budget are redesigned.')
param maxReplicas int = 1

@minValue(1)
@description('Azure Files share quota in GiB; storage and transactions can incur charges.')
param shareQuotaGiB int = 5

@minValue(1)
@description('Monthly resource-group cost budget, in USD. An alert does not stop spending.')
param budgetAmountUsd int = 25

@minValue(1)
@description('First actual-spend alert in USD; must be below budgetAmountUsd.')
param budgetEarlyUsd int = 5

@minValue(1)
@description('Second actual-spend alert in USD; must be below budgetAmountUsd.')
param budgetLateUsd int = 20

@description('Budget period start: Azure requires the first day of a month. Supply a stable UTC date on repeat deployments.')
param budgetStartDate string = utcNow('yyyy-MM-01T00:00:00Z')

@minValue(0)
@description('Approved chat model-call ceiling per day. Zero keeps paid model calls closed.')
param modelDailyCalls int = 0
@minValue(0)
@description('Approved Arena model-call ceiling per day. Zero keeps paid Arena calls closed.')
param arenaDailyCalls int = 0
@description('Approved chat model spend ceiling in USD per day; zero keeps priced calls closed.')
param modelDailyUsd string = '0'
@description('Approved Arena model spend ceiling in USD per day; zero keeps priced calls closed.')
param arenaDailyUsd string = '0'

@secure()
@description('Key of the stweb account, read by the operator after the first provision. Empty: no mount and no web app.')
param stateStorageKey string = ''

@secure()
@description('Optional operator login secret; empty keeps the public console locked.')
param operatorToken string = ''

@secure()
@description('Optional server-side model endpoint; never use a Mac localhost address here.')
param modelBaseUrl string = ''

@secure()
@description('Optional server-side model name. Requires modelBaseUrl.')
param modelName string = ''

@secure()
@description('Optional server-side model key. Never put a value in source or client code.')
param modelApiKey string = ''

var port = 8090
var hasRegistry = !empty(registryName) && !empty(registryLoginServer)
var hasModel = !empty(modelBaseUrl) && !empty(modelName)
var hasStateKey = !empty(stateStorageKey)
var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: environmentName
}

// Azure Files in Container Apps uses an account key; the lake account forbids shared keys.
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stweb${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: true
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource stateShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'nabiz-web-state'
  properties: {
    shareQuota: shareQuotaGiB
    enabledProtocols: 'SMB'
  }
}

// The template never reads a key (tests/test_infra.py); the operator supplies it as a secure parameter.
resource stateMount 'Microsoft.App/managedEnvironments/storages@2024-03-01' = if (hasStateKey) {
  parent: environment
  name: 'nabiz-web-state'
  properties: {
    azureFile: {
      accountName: storageAccount.name
      accountKey: stateStorageKey
      shareName: stateShare.name
      accessMode: 'ReadWrite'
    }
  }
}

resource webIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-web-${resourceToken}'
  location: location
  tags: tags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (hasRegistry) {
  name: registryName
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasRegistry) {
  name: guid(registry.id, webIdentity.id, acrPullRole)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
    principalId: webIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// No state key, no web app: container storage is not durable, so it never serves without the share.
resource web 'Microsoft.App/containerApps@2024-03-01' = if (hasStateKey) {
  name: 'ca-web-${resourceToken}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${webIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: port
        transport: 'auto'
        allowInsecure: false
      }
      registries: hasRegistry ? [
        {
          server: registryLoginServer
          identity: webIdentity.id
        }
      ] : []
      secrets: concat(
        !empty(operatorToken) ? [{ name: 'operator-token', value: operatorToken }] : [],
        hasModel ? [
          { name: 'model-base-url', value: modelBaseUrl }
          { name: 'model-name', value: modelName }
        ] : [],
        hasModel && !empty(modelApiKey) ? [{ name: 'model-api-key', value: modelApiKey }] : []
      )
    }
    template: {
      containers: [
        {
          name: 'nabiz-web'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(
            [
              { name: 'NABIZ_ENV_FILE', value: '/dev/null' }
              { name: 'NABIZ_HOST', value: '0.0.0.0' }
              { name: 'NABIZ_CONSOLE_PORT', value: '8090' }
              { name: 'NABIZ_OFFLINE', value: offlineMode ? '1' : '0' }
              { name: 'NABIZ_LLM_NO_PROBE', value: '1' }
              { name: 'NABIZ_LADDER_LOCAL_ON_CAP', value: '0' }
              { name: 'NABIZ_LLM_DAILY_CALLS', value: string(modelDailyCalls) }
              { name: 'NABIZ_ARENA_DAILY_CALLS', value: string(arenaDailyCalls) }
              { name: 'NABIZ_LLM_DAILY_USD', value: modelDailyUsd }
              { name: 'NABIZ_ARENA_DAILY_USD', value: arenaDailyUsd }
              { name: 'NEXUS_DB_PATH', value: '/var/lib/nabiz/nexus/nexus.db' }
              { name: 'NABIZ_ACCOUNTS_DB', value: '/var/lib/nabiz/accounts/accounts.sqlite' }
              { name: 'NABIZ_REQUESTS_DB_PATH', value: '/var/lib/nabiz/nexus/citizen_requests.db' }
              { name: 'NABIZ_CHAT_PAUSE_PATH', value: '/var/lib/nabiz/nexus/chat_paused.json' }
              { name: 'NABIZ_LLM_SPEND_FILE', value: '/var/lib/nabiz/console/llm_spend.json' }
              { name: 'NABIZ_OUTBOX_DIR', value: '/var/lib/nabiz/outbox' }
              { name: 'NABIZ_LAKE_DIR', value: '/var/lib/nabiz/lake' }
              { name: 'NABIZ_KNOWLEDGE_DB', value: '/var/lib/nabiz/knowledge/knowledge.db' }
              // P00 D2a (I): every file the app writes lives on the share; the root covers any store without its own name.
              { name: 'NABIZ_DATA_ROOT', value: '/var/lib/nabiz' }
              { name: 'NABIZ_QUOTA_DB', value: '/var/lib/nabiz/accounts/quota.sqlite' }
              { name: 'NABIZ_SESSIONS_DB', value: '/var/lib/nabiz/accounts/sessions.sqlite' }
              { name: 'NABIZ_APPEALS_DB', value: '/var/lib/nabiz/accounts/appeals.sqlite' }
              { name: 'NABIZ_PLAN_DB_PATH', value: '/var/lib/nabiz/nexus/plans.sqlite3' }
              { name: 'NABIZ_JOURNEY_WATCH_DB_PATH', value: '/var/lib/nabiz/accounts/journey_watch.sqlite' }
              { name: 'NABIZ_BOOKING_DB_PATH', value: '/var/lib/nabiz/accounts/bookings.sqlite' }
              { name: 'NABIZ_ESCORT_DB_PATH', value: '/var/lib/nabiz/nexus/escort.sqlite' }
              { name: 'NABIZ_INCIDENTS_DB_PATH', value: '/var/lib/nabiz/nexus/incidents.sqlite' }
              { name: 'NABIZ_PHOTO_REPORTS_DB_PATH', value: '/var/lib/nabiz/nexus/photo_reports.sqlite' }
              { name: 'NABIZ_REPORT_TIMELINE_DB_PATH', value: '/var/lib/nabiz/nexus/report_timeline.sqlite' }
              { name: 'NABIZ_POLLS_DB_PATH', value: '/var/lib/nabiz/nexus/polls.sqlite' }
              { name: 'NABIZ_OUTAGE_DB_PATH', value: '/var/lib/nabiz/nexus/outage_watch.sqlite' }
              { name: 'NABIZ_OUTCOMES_DB_PATH', value: '/var/lib/nabiz/nexus/outcomes.sqlite' }
              { name: 'NABIZ_SCENARIOS_DB_PATH', value: '/var/lib/nabiz/nexus/scenarios.sqlite' }
              { name: 'NABIZ_KNOWLEDGE_EDITOR_DB_PATH', value: '/var/lib/nabiz/knowledge/editor.sqlite' }
              { name: 'NABIZ_SOURCE_CANDIDATES_PATH', value: '/var/lib/nabiz/knowledge/source_candidates.jsonl' }
            ],
            !empty(operatorToken) ? [{ name: 'NABIZ_CONSOLE_TOKEN', secretRef: 'operator-token' }] : [],
            hasModel ? [
              { name: 'NABIZ_LLM_BASE_URL', secretRef: 'model-base-url' }
              { name: 'NABIZ_LLM_MODEL', secretRef: 'model-name' }
            ] : [],
            hasModel && !empty(modelApiKey) ? [{ name: 'NABIZ_LLM_API_KEY', secretRef: 'model-api-key' }] : []
          )
          volumeMounts: [
            {
              volumeName: 'state'
              mountPath: '/var/lib/nabiz'
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: port
              }
              periodSeconds: 30
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'state'
          storageType: 'AzureFile'
          storageName: stateMount.name
        }
      ]
      scale: {
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
  dependsOn: [acrPull, stateMount]
}

// Notifications target the resource-group Owner role. No personal address is in source.
// Azure budget notifications are advisory: they do not cap or shut down resources.
resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: 'budget-web-${resourceToken}'
  properties: {
    category: 'Cost'
    amount: budgetAmountUsd
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      early: {
        enabled: true
        operator: 'GreaterThan'
        threshold: budgetEarlyUsd * 100 / budgetAmountUsd
        thresholdType: 'Actual'
        contactRoles: ['Owner']
      }
      late: {
        enabled: true
        operator: 'GreaterThan'
        threshold: budgetLateUsd * 100 / budgetAmountUsd
        thresholdType: 'Actual'
        contactRoles: ['Owner']
      }
    }
  }
}

output webName string = hasStateKey ? web.name : ''
output webUri string = hasStateKey ? 'https://${web!.properties.configuration.ingress.fqdn}' : ''
output stateStorageAccountName string = storageAccount.name
output stateShareName string = stateShare.name
output budgetName string = budget.name
