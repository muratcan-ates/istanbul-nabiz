// The collector as scheduled Container Apps Jobs (DECISIONS #10).
//
// One Microsoft.App/jobs resource per entry in `schedules`, all running the same image as
// the MCP server with a different command: `python -m nabiz.collector.job --sources ...`
// (src/nabiz/collector/job.py). Each execution is a fresh container that reads a few
// İBB sources, writes them to the lake (and to ADX when configured) and exits.
//
// Why jobs rather than the Function's timers or the laptop: a job cannot fall asleep with
// the lid, and unlike the Function it runs the watched-line snapshots and the ETA
// prediction log that the measured ETA error depends on. The decision record has the rest.
//
// COST — the thing that ends a student subscription, so it is stated per setting:
//   * Consumption only. The environment in containerapps.bicep has no workload profiles and
//     no `workloadProfileName` is set here, so executions bill per second of vCPU and GiB
//     at the Consumption active rate, and nothing at all between executions.
//   * 0.25 vCPU / 0.5 GiB, the smallest Consumption pair. The heaviest execution measured
//     locally (watched lines with the GTFS index loaded, offline fixtures) peaked at about
//     101 MiB resident; see DECISIONS #10 for the monthly arithmetic against the free grant.
//   * parallelism 1, replicaCompletionCount 1: one replica per execution. There is nothing
//     to parallelise, and a second replica would be a second, independent İETT budget.
//   * replicaRetryLimit 0: a failed execution is not retried. A retry is an unplanned İETT
//     request; the next scheduled execution — three minutes away for the busiest job — is
//     the retry.
//   * No secrets. Storage and ADX are reached with the collector's managed identity, the
//     image is pulled with the same identity (AcrPull, granted in containerapps.bicep), and
//     there is nothing to put in `configuration.secrets`.
//
// Schema: Microsoft.App/jobs@2024-03-01, the same API version as the managed environment
// and the container app next door. Property names checked against the Bicep reference at
// learn.microsoft.com/azure/templates/microsoft.app/2024-03-01/jobs on 2026-09-23.

@description('Region for the jobs; must be the managed environment region.')
param location string

@description('Tags applied to every job.')
param tags object

@description('Stable per-environment suffix for resource names.')
param resourceToken string

@description('Resource id of the Container Apps managed environment (Consumption-only) the jobs run in.')
param environmentId string

@description('Login server of the Azure Container Registry holding the image, e.g. cr<token>.azurecr.io. Empty when the image comes from a registry that allows anonymous pull.')
param registryLoginServer string = ''

@description('Name of the existing collector identity (modules/collectoridentity.bicep). Used for the image pull, the lake and ADX.')
param collectorIdentityName string

@description('Name of the existing storage account holding the lake.')
param storageAccountName string

@description('Container the collector writes bronze snapshots to (NABIZ_LAKE_CONTAINER).')
param bronzeContainerName string

@description('ADX free cluster URI. Empty is valid; the jobs then write the lake only.')
param kustoUri string = ''

@description('ADX database name.')
param kustoDatabase string = 'nabiz'

@description('Image to run: the MCP server image, which also carries the collector (see the Dockerfile).')
param image string

@description('One entry per job: name, cron (five fields, UTC), sources (as --sources takes them) and replicaTimeout (seconds).')
param schedules array

@description('vCPU per execution, as a string because Bicep has no float literal. With memory, must be a valid Consumption pair.')
param cpu string = '0.25'

@description('Memory per execution. 0.25 vCPU pairs with 0.5Gi on Consumption.')
param memory string = '0.5Gi'

@description('Seconds kept back from replicaTimeout so the job stops reading in time to write what it read. Mirrors nabiz.collector.job.DEADLINE_MARGIN_S.')
param deadlineMarginSeconds int = 30

resource collectorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: collectorIdentityName
}

resource collectorJobs 'Microsoft.App/jobs@2024-03-01' = [
  for schedule in schedules: {
    // caj-<name>-<13-char token>: at most 28 characters for the names used here. The
    // naming-rules page has no row for jobs; the container-app rule (2-32, lowercase
    // letters, digits and hyphens) is applied, and tests/test_collector_job.py checks it.
    name: 'caj-${schedule.name}-${resourceToken}'
    location: location
    tags: tags
    identity: {
      type: 'UserAssigned'
      userAssignedIdentities: {
        '${collectorIdentity.id}': {}
      }
    }
    properties: {
      environmentId: environmentId
      configuration: {
        triggerType: 'Schedule'
        scheduleTriggerConfig: {
          cronExpression: schedule.cron
          parallelism: 1
          replicaCompletionCount: 1
        }
        replicaTimeout: schedule.replicaTimeout
        replicaRetryLimit: 0
        registries: empty(registryLoginServer)
          ? []
          : [
              {
                server: registryLoginServer
                identity: collectorIdentity.id
              }
            ]
      }
      template: {
        containers: [
          {
            name: 'collector'
            image: image
            // The image's CMD starts the MCP server; `command` replaces the entrypoint and
            // `args` the CMD, so the same image runs one collector tick instead.
            command: [
              'python'
              '-m'
              'nabiz.collector.job'
            ]
            args: [
              '--sources'
              schedule.sources
              '--deadline-s'
              string(schedule.replicaTimeout - deadlineMarginSeconds)
            ]
            resources: {
              cpu: json(cpu)
              memory: memory
            }
            env: [
              // DefaultAzureCredential (lake) picks the user-assigned identity from this.
              {
                name: 'AZURE_CLIENT_ID'
                value: collectorIdentity.properties.clientId
              }
              // Its presence switches nabiz.collector.lake from data/lake to ADLS Gen2.
              {
                name: 'AZURE_STORAGE_ACCOUNT'
                value: storageAccountName
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
              // nabiz.collector.kusto needs the client id named: a user-assigned identity
              // cannot be inferred when several could apply.
              {
                name: 'NABIZ_KUSTO_MI_CLIENT_ID'
                value: collectorIdentity.properties.clientId
              }
            ]
          }
        ]
      }
    }
  }
]

output jobNames array = [for i in range(0, length(schedules)): collectorJobs[i].name]
