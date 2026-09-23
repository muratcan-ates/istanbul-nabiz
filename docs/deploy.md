# Deploying İstanbul Nabız to Azure

Everything in `infra/` plus `azure.yaml` exists so that the whole system — the collector, the
lake and the MCP server — comes up from the command line:

```bash
azd up          # infrastructure, image build in ACR, MCP server
azd provision   # once more, so the collector jobs get the image azd just built
```

This document is the honest version of those two lines: what the template creates, the gates
that have to pass before it will deploy on an Azure for Students subscription, what it costs, how
the collector moves off the laptop, what is still missing, and how to take it all down again.

> **Status, 23 September 2026.** The template is written and reviewed but **has never been
> deployed**, and neither `az` nor `azd` nor Docker is installed on the development machine — see
> [How this was verified](#how-this-was-verified). Since DECISIONS #10 the collector runs as five
> scheduled **Container Apps Jobs** from the MCP server's image; the Azure Function it replaces is
> still in the template, off by default. The `Dockerfile` exists (DECISIONS #11) but has not been
> built; its first build is the owner's `azd deploy mcp`.

---

## 1. What gets deployed

`infra/main.bicep` is deployed at **subscription scope**. It creates the resource group itself
(`rg-<environmentName>`, overridable), so `azd up` works against a subscription with nothing in
it, and `azd down` removes the group with everything inside it.

| Resource | Type · API version | Why it is here |
|---|---|---|
| Resource group | `Microsoft.Resources/resourceGroups@2024-03-01` | One group per azd environment; the unit of teardown |
| Log Analytics workspace | `Microsoft.OperationalInsights/workspaces@2023-09-01` | 30-day retention, **hard daily ingestion cap** (default 0.16 GB: the 5 GB/month grant over 31 days) |
| Application Insights | `Microsoft.Insights/components@2020-02-02` | Workspace-based; the agent → tool → model trace |
| Storage account (ADLS Gen2) | `Microsoft.Storage/storageAccounts@2023-05-01` | `isHnsEnabled: true`, Standard_LRS, **shared keys disabled**. The lake; also the Function's host storage if that is ever enabled |
| Blob service + 4 containers | `.../blobServices@2023-05-01`, `.../containers@2023-05-01` | `bronze`, `silver`, `gold`, `deployments` |
| Lifecycle policy | `.../managementPolicies@2023-05-01` | Deletes `bronze/` after 30 days. A volume bound, **not** a privacy control — and it deletes *all* collected history, see the note below |
| Collector identity | `Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31` | `modules/collectoridentity.bicep`. One client id for the ADX grant whichever host runs the collector |
| MCP identity | `Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31` | Holds AcrPull before the first image pull |
| Container registry | `Microsoft.ContainerRegistry/registries@2023-07-01` | Basic, **no admin user**; target of azd remote build (optional — see cost) |
| Container Apps environment | `Microsoft.App/managedEnvironments@2024-03-01` | Consumption-only (no workload profiles), logs to Azure Monitor |
| Environment diagnostics | `Microsoft.Insights/diagnosticSettings@2021-05-01-preview` | Console + system logs to the workspace **without a shared key** |
| Container app (MCP server) | `Microsoft.App/containerApps@2024-03-01` | `minReplicas: 0`, **`maxReplicas: 1`**, ingress on 8000 |
| **Collector jobs × 5** | `Microsoft.App/jobs@2024-03-01` | `modules/collectorjobs.bicep`. Scheduled, 0.25 vCPU / 0.5 GiB, one replica, no retries, no secrets. **Created only once an image exists** (DECISIONS #12) |
| Flex Consumption plan + Function app | `Microsoft.Web/serverfarms@2023-12-01`, `Microsoft.Web/sites@2023-12-01` | **Off by default** (`deployCollectorFunction`); the superseded collector, kept as a fallback |
| Azure Maps (optional) | `Microsoft.Maps/accounts@2023-06-01` | Gen2 / G2, `location: 'global'`, `disableLocalAuth: false` (see §3). **Off by default** |
| Role assignments | `Microsoft.Authorization/roleAssignments@2022-04-01` | Below |

The five jobs, from `python -m nabiz.collector.job --plan` (cron is UTC):

| Job | Cron | Reads | İETT requests / run | Peak runs / hour | `replicaTimeout` |
|---|---|---|---|---|---|
| `caj-lines-<token>` | `*/3 * * * *` | watched lines 500T, 34, 15F + the ETA prediction log | 3 | 20 | 170 s |
| `caj-city-<token>` | `1-59/10 * * * *` | İSPARK, whole İETT fleet | 1 | 6 | 300 s |
| `caj-metro-<token>` | `5 * * * *` | Metro İstanbul notices | 0 | 1 | 300 s |
| `caj-traffic-<token>` | `10 */6 * * *` | traffic index, last 7 hours | 0 | 1 | 300 s |
| `caj-airquality-<token>` | `16 */12 * * *` | air quality, 28 stations, last 24 hours | 0 | 1 | 900 s |

In the peak hour that is **66 İETT requests**, under `PoliteClient`'s 80 and İETT's documented 100.
Because a job execution is a fresh process, that bound comes from the schedule rather than from an
in-process counter; `tests/test_collector_job.py` recomputes it, and checks that the schedule in
`infra/main.bicep` is the one in `src/nabiz/collector/job.py`. The reasoning, and the alternatives, are
DECISIONS #10.

> **The 30-day bronze rule is a cost bound, not a privacy control — and it is where the history
> goes.** The bus number plate never reaches this account: `BusPosition.from_fleet_raw` drops it in
> the parser, the snapshots only ever see parsed models, and the lake writer stores those rows
> (DECISIONS #7, and the promise in `NOTICE.md` that the plate is never written to the lake). What
> the rule *does* delete is everything the collector has ever written, because every source lands
> under `bronze/` (`NABIZ_LAKE_CONTAINER=bronze`). With no ADX cluster attached, and without the
> local sync in §4.5, "usually at this hour" and the ETA error can never look back further than
> `NABIZ_BRONZE_RETENTION_DAYS`. Raise it, attach ADX, or sync before you rely on a longer window.
> If bronze is ever changed to hold the verbatim upstream body that DECISIONS #6 describes, the
> plate comes back with it and `NOTICE.md` has to be corrected *before* that change ships.

> **Only if you enable the Function: one storage account would be both the lake and the Functions
> host.** The account has `isHnsEnabled: true` for Delta's sake, and Azure Functions is *not* on
> Microsoft's
> [list of Azure services that support hierarchical namespace](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-supported-azure-services).
> Nothing documents the combination as forbidden — but it has never been deployed. Symptoms would be
> a deployment package that never appears in `deployments/` or timers that never fire; the fix is a
> second plain `StorageV2` account (`isHnsEnabled: false`) for the function app. The jobs do not use
> host storage and are not affected. The lifecycle rule is scoped with `prefixMatch: ['bronze/']`, which
> keeps it away from the containers a Functions host owns.

### Role assignments — the whole list

Nothing in this template contains a key, a connection string with a secret, or a `listKeys()`
call. Every component authenticates with a managed identity.

| Identity | Role | Scope | Why |
|---|---|---|---|
| Collector | Storage Blob Data **Contributor** | storage account | The collector's bronze writes — the least privilege the code needs (`collectoridentity.bicep`) |
| Collector | **AcrPull** | container registry | The jobs pull the image with the collector's own identity (`containerapps.bicep`) |
| Collector, Function only | Storage Blob Data **Owner** | storage account | The Functions host takes blob **leases** for timer singleton locks and reads its own deployment package |
| Collector, Function only | Storage **Queue** / **Table** Data Contributor | storage account | Identity-based `AzureWebJobsStorage` host bookkeeping |
| Collector, Function only | **Monitoring Metrics Publisher** | Application Insights | Telemetry with Entra auth rather than the instrumentation key |
| MCP server | AcrPull | container registry | Pull without a registry password |
| MCP server | Storage Blob Data **Reader** | storage account | Read-only: the collector writes the lake, the server only reads it |
| MCP server | Monitoring Metrics Publisher | Application Insights | Same as above |
| MCP server | Azure Maps Data Reader | Maps account | Only when `deployMaps=true`; mints browser tokens instead of embedding a subscription key |
| You (`AZURE_PRINCIPAL_ID`) | Storage Blob Data Contributor | storage account | So the cloud lake can be synced down (§4.5) and the collector run locally against it |

### What is deliberately *not* in the template

| Not deployed | Why |
|---|---|
| **Azure AI Search** | Basic is ~$2.42/day **even idle** — the whole student credit in six weeks. There is no retrieval layer in this design: every tool is parametric (DECISIONS #2) |
| **Stream Analytics** | No free tier at all; the scheduled jobs do the same job for cents |
| **Data Factory** | Data flows bill per vCore-hour |
| Anything from **Marketplace** | Bills outside the Azure credit and can charge a card directly |
| **Azure Data Explorer** | The free cluster has **no ARM resource provider** — it cannot be expressed in Bicep. Created by hand, see [section 6](#6-the-azure-data-explorer-free-cluster) |
| **Key Vault** | Nothing to put in it. Adding one would mean inventing a secret |
| **Workload profiles** | A Dedicated profile bills per hour; the free grant covers Consumption only. `tests/test_collector_job.py` fails if a job names one |

---

## 2. Prerequisites

Neither tool is installed on the development machine yet; installing them is the owner's first step:

```bash
brew install azure-cli
brew install azd                       # or: curl -fsSL https://aka.ms/install-azd.sh | bash
az version && azd version
az extension add --name containerapp --upgrade   # the `az containerapp job …` commands used below
```

You do **not** need Docker. `azure.yaml` sets `remoteBuild: true`, so the image is built inside
Azure Container Registry — which also sidesteps the arm64 vs linux/amd64 problem.

```bash
az login
az account show -o table               # confirm the Azure for Students subscription is Enabled
azd auth login
```

Register the resource providers once per subscription (each takes a few minutes, and an
unregistered provider fails at *deploy* time, not at plan time):

```bash
for p in Microsoft.Resources Microsoft.Storage Microsoft.Web Microsoft.App \
         Microsoft.ContainerRegistry Microsoft.OperationalInsights Microsoft.Insights \
         Microsoft.ManagedIdentity Microsoft.Maps Microsoft.Consumption; do
  az provider register -n $p
done
az provider list --query "[?registrationState!='Registered' && contains('Microsoft.App Microsoft.Web Microsoft.Storage Microsoft.ContainerRegistry Microsoft.Maps', namespace)].{ns:namespace, state:registrationState}" -o table
```

`scripts/probe_day0.py --azure` reports provider state as check **A4** and never registers
anything itself.

**Before the first provision, create the budget alerts in [§7](#budget-alerts--before-anything-can-spend).**

---

## 3. The Day-0 region gate

Azure for Students carries a hidden **"Allowed resource deployment regions"** policy. It typically
permits about five regions, and *the list differs per subscription*. A region outside it fails the
deployment with `RequestDisallowedByPolicy`. The region must also offer **Container Apps** — jobs
included — and, only if you re-enable the Function collector, **Functions Flex Consumption**.

```bash
# What region policies exist at all (read the display names — the built-in is "Allowed locations")
az policy assignment list --query "[].{name:displayName, definition:policyDefinitionId}" -o table

# (a) regions the policy allows, normalised to short names
az policy assignment list --query "[].parameters.listOfAllowedLocations.value[]" -o tsv \
  | tr -d ' ' | tr '[:upper:]' '[:lower:]' | sort -u > /tmp/allowed.txt

# (b) regions that offer Container Apps jobs (display names — same normalisation)
az provider show --namespace Microsoft.App \
  --query "resourceTypes[?resourceType=='jobs'].locations[]" -o tsv \
  | tr -d ' ' | tr '[:upper:]' '[:lower:]' | sort -u > /tmp/aca.txt

# (c) pick from the intersection
comm -12 /tmp/allowed.txt /tmp/aca.txt

# Only if you set DEPLOY_COLLECTOR_FUNCTION=true: intersect with Flex Consumption as well
az functionapp list-flexconsumption-locations --query "[].name" -o tsv \
  | tr -d ' ' | tr '[:upper:]' '[:lower:]' | sort -u > /tmp/flex.txt
comm -12 /tmp/allowed.txt /tmp/flex.txt
```

The normalisations are idempotent: policy parameters usually hold short names (`westeurope`) and
the provider listings return display names (`West Europe`); the pipeline turns either into the same
thing. If `/tmp/allowed.txt` comes back empty there is **no** region policy on the subscription —
confirm that rather than assume it, because the failure arrives half way through `azd up`, after
the resource group already exists.

If the intersection is empty: request a policy exemption, or keep the laptop collector running and
deploy nothing (DECISIONS #10 lists what that costs in lost history).

`scripts/probe_day0.py --azure` runs the policy check as **A2** and the intersection above, (a) with
(b), as **A3**. Flex Consumption is left to the last command, since it only matters for the optional
Function. The report it writes, `docs/day0_report.json`, is tracked; since 23 Sep it records the
subscription's name and state but not its id, the tenant id or the signed-in account.

Azure Maps is a separate gate: it is `location: 'global'`, so the region policy either permits
`Microsoft.Maps` or it does not. That is why `deployMaps` defaults to **false**. Turn it on
deliberately with `azd env set DEPLOY_MAPS true && azd provision`. The account keeps
**subscription keys enabled** (`disableLocalAuth: false`), because `src/nabiz/web/main.py` reads
`NABIZ_MAPS_KEY` today; the template never emits that key. Fetch it deliberately when you need it:

```bash
az maps account keys list -n <maps-account> -g $(azd env get-value AZURE_RESOURCE_GROUP) \
  --query primaryKey -o tsv
```

---

## 4. Deploy, and move the collector off the laptop

### 4.1 First run: `azd up`

```bash
cd istanbul-nabiz                     # the repository root
azd env new nabiz-dev                 # environment name -> rg-nabiz-dev, and the azd-env-name tag
azd env set AZURE_LOCATION westeurope # a region from the intersection in section 3
azd up
```

`azd up` provisions `infra/main.bicep`, builds the `Dockerfile` in Azure Container Registry and
deploys it to the one azd service, `mcp` (matched by the tag `azd-service-name: mcp`). On this
first run the **collector jobs are skipped**: there is no image yet, and a job deployed with a
placeholder image would run a web server until `replicaTimeout` on every tick and bill for it
(DECISIONS #12). The `postprovision` hook says so: `Collector: NOT deployed yet`.

The laptop collector can keep running during this step; nothing in Azure calls İBB yet.

### 4.2 Check the image azd recorded

```bash
azd env get-value SERVICE_MCP_IMAGE_NAME
# e.g. cr<token>.azurecr.io/istanbul-nabiz/mcp-nabiz-dev:azd-deploy-<timestamp>
```

`infra/main.parameters.json` feeds that value into the template as `mcpDeployedImage`. If it
prints nothing (the one assumption here not verified against a real azd), set it from the running
app instead:

```bash
azd env set SERVICE_MCP_IMAGE_NAME "$(az containerapp show -n "$(azd env get-value SERVICE_MCP_NAME)" \
  -g "$(azd env get-value AZURE_RESOURCE_GROUP)" --query 'properties.template.containers[0].image' -o tsv)"
```

### 4.3 Cut over: stop the laptop, then create the jobs

The order matters. The jobs plan 66 İETT requests in their peak hour; the laptop collector allows
itself 80 per hour (DECISIONS #3); İETT documents 100. Running both, even for an hour, can exceed it.

```bash
make collect-stop                     # stops scripts/supervise_collector.sh and the collector
pgrep -fl collect_forever.py          # must print nothing
azd provision                         # creates the five jobs with the image from 4.2
```

The hook now prints `Collector: Container Apps Jobs deployed`. The minutes between the stop and the
first execution are a gap in the series; that is accepted, and smaller than any of the laptop's.

If the jobs turn out not to work (§4.4), **pause them first** (§8), and only then restart the
laptop with `make collect-supervise` — never both at once.

### 4.4 Verify the jobs, and measure what they cost

```bash
RG=$(azd env get-value AZURE_RESOURCE_GROUP)
az containerapp job list -g "$RG" -o table        # five jobs: caj-lines-…, caj-city-…, caj-metro-…, caj-traffic-…, caj-airquality-…

LINES=$(az containerapp job list -g "$RG" --query "[?starts_with(name, 'caj-lines-')].name | [0]" -o tsv)
az containerapp job start -n "$LINES" -g "$RG"    # optional: one execution now (3 İETT requests; 69 in that hour, still under 80)
az containerapp job execution list -n "$LINES" -g "$RG" -o table
```

Within ten minutes new blobs should appear under `bronze/`:

```bash
az storage blob list --account-name "$(azd env get-value NABIZ_STORAGE_ACCOUNT)" -c bronze \
  --auth-mode login --prefix iett_line_snapshot/ --num-results 5 -o table
```

Every execution ends with one JSON line tagged `collector-job`. This Log Analytics query (portal →
the `log-<token>` workspace → Logs) shows outcomes per job for the last day. It is written against
the documented `ContainerAppConsoleLogs` columns but has not been run against a workspace yet:

```kusto
ContainerAppConsoleLogs
| where TimeGenerated > ago(24h)
| where Log contains "collector-job {"
| extend summary = parse_json(substring(Log, indexof(Log, "{")))
| extend exit_code = toint(summary.exit_code), sources = strcat_array(summary.sources, ",")
| summarize executions = count(), failed = countif(exit_code != 0), last = max(TimeGenerated) by sources
```

A `lines` execution that logs `eta_predictions failed` means the image was built without
`data/reference/gtfs` (the build log says `WARNING: no GTFS reference`). Positions are still written;
predictions are not.

**Measure the cost after a day.** DECISIONS #10 estimates the jobs from the laptop's run times plus
an *assumed* 20 s container start, which puts them at 90 % of the monthly free grant. Replace the
assumption with real durations:

```bash
az containerapp job execution list -n "$LINES" -g "$RG" \
  --query "[].{status:properties.status, start:properties.startTime, end:properties.endTime}" -o table
```

Multiply the median duration by 14,400 executions a month for `lines` (and likewise for the
others: 4,320 · 720 · 120 · 60), by 0.25 vCPU and 0.5 GiB, and compare with the free 180,000
vCPU-seconds and 360,000 GiB-seconds.

### 4.5 Read the cloud lake locally

`scripts/eta_report.py`, `calibrate_eta.py` and `reliability_report.py` read `data/lake/`. The jobs
write the same layout to the `bronze` container, and blob names are derived from their content, so
downloading into the local lake never duplicates a file:

```bash
az storage blob download-batch --account-name "$(azd env get-value NABIZ_STORAGE_ACCOUNT)" \
  --source bronze --destination data/lake --auth-mode login \
  --pattern 'iett_line_snapshot/*'
az storage blob download-batch --account-name "$(azd env get-value NABIZ_STORAGE_ACCOUNT)" \
  --source bronze --destination data/lake --auth-mode login \
  --pattern 'eta_predictions/*'
make eta
```

Do this at least once every `NABIZ_BRONZE_RETENTION_DAYS` (30 by default): the lifecycle rule
deletes cloud history that has not been synced or ingested into ADX.

### 4.6 After a code change

```bash
azd deploy mcp      # rebuild the image in ACR, roll the MCP server
azd provision       # roll the same image to the five jobs
```

The `mcp` service's `postdeploy` hook prints that reminder. Until the provision, the jobs keep the
previous image and keep collecting. A provision no longer reverts the MCP server to the placeholder
image (DECISIONS #12).

### Knobs

Every parameter in `infra/main.parameters.json` reads an azd environment variable, so nothing
needs editing to change behaviour:

| `azd env set …` | Default | Effect |
|---|---|---|
| `DEPLOY_CONTAINER_APP` | `true` | `false` skips the Container App, its environment and the registry — **and therefore the collector jobs** |
| `DEPLOY_CONTAINER_REGISTRY` | `true` | `false` keeps the Container App but drops the ~$1.17/week registry; you must then set `MCP_CONTAINER_IMAGE` |
| `MCP_CONTAINER_IMAGE` | *(empty)* | Pin an image from a registry that allows anonymous pull, for the server and the jobs |
| `SERVICE_MCP_IMAGE_NAME` | *(set by azd)* | The image azd last deployed; the jobs run it (§4.2) |
| `DEPLOY_COLLECTOR_JOBS` | `true` | `false` stops a provision from creating the jobs; it does **not** delete existing ones (§8) |
| `DEPLOY_COLLECTOR_FUNCTION` | `false` | `true` adds the superseded Function collector. Never together with the jobs: two İETT budgets |
| `DEPLOY_MAPS` | `false` | `true` adds the Azure Maps G2 account |
| `NABIZ_KUSTO_URI` | *(empty)* | ADX free cluster URI; empty is a valid state |
| `NABIZ_KUSTO_DB` | `nabiz` | ADX database |
| `NABIZ_BRONZE_RETENTION_DAYS` | `30` | Lifecycle deletion age for raw bronze |
| `NABIZ_MCP_MAX_REPLICAS` | `1` | Replica ceiling — see the warning below |
| `NABIZ_DAILY_LOG_CAP_GB` | `0.16` | Log Analytics daily ingestion cap; 0.16 × 31 days = 4.96 GB, inside the 5 GB/month grant |
| `NABIZ_RESOURCE_GROUP` | *(empty)* | Override the `rg-<env>` name |

The MCP server's own edge is configured on the Container App's environment rather than through azd
parameters; the template sets only the proxy hop. Defaults are those of `HardeningConfig` in
`src/ibb_mcp/config.py`:

| MCP server edge (Container App environment) | Default | Effect |
|---|---|---|
| `NABIZ_API_KEYS` | empty = open | Comma-separated keys accepted in `X-API-Key`; add as a Container Apps secret reference, never a plain value |
| `NABIZ_MCP_RATE_BURST` | `30` | Token-bucket size per caller; each tool call costs its price in `TOOL_COSTS` |
| `NABIZ_MCP_RATE_PER_MINUTE` | `12` | Tokens refilled per minute per caller |
| `NABIZ_MCP_MAX_CLIENTS` | `1024` | Callers remembered at once, as salted pseudonyms in memory |
| `NABIZ_MCP_CORS_ORIGINS` | empty = closed | Origins allowed to call from a browser |
| `NABIZ_MCP_TRUSTED_PROXY_HOPS` | `0`; the template sets `1` | Proxies whose `X-Forwarded-For` entry is trusted (§5) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | set by the template | Spans are exported only when the image installs the `telemetry` extra, which the `Dockerfile` does not today |

The container also has a liveness probe on `/healthz`, every 30 s; that path answers from process state
and local files and never calls İBB.

The job schedules are the `collectorJobSchedules` default in `infra/main.bicep`, not an azd
variable: they must stay equal to `SCHEDULES` in `src/nabiz/collector/job.py`, where the İETT
arithmetic is tested. Change both, run `make test`, then `azd provision`.

> **Do not raise `NABIZ_MCP_MAX_REPLICAS` above 1.** The İETT hourly budget and the TTL cache
> live *in process* (`ibb_mcp.http.PoliteClient`: `HourlyBudget("iett", limit=80)` and a 6 s gate
> on `api.ibb.gov.tr`). Two replicas are two independent budgets — up to **160 requests/hour**
> against a service documented at 100. Even at one replica, the server's 80 and the jobs' 66 are
> separate budgets; an hour of heavy İETT use through the MCP server can push the total past 100.
> That exposure is open (DECISIONS #10, consequences).

> **azd substitutes `${VAR}` as text.** Boolean and numeric parameters must be spelled exactly
> `true` / `false` / `30` — `True`, `yes` or `"true"` will fail ARM's type check with a message
> that does not mention azd.

---

## 5. What is still missing

- **The trusted proxy hop, confirmed live.** `NABIZ_MCP_TRUSTED_PROXY_HOPS=1` is set on the Container
  App (`infra/modules/containerapps.bicep`), so the server reads each caller's address from the entry
  the ingress appends to `X-Forwarded-For` and every caller gets its own rate budget. On the first
  deploy, confirm that the ingress appends exactly one entry; with the wrong count every caller shares
  one budget, or a caller can forge its own.
- **The base image is not pinned by digest** (`docs/THREAT_MODEL.md`, SC-5). Pinning needs the
  current digest of `python:3.12-slim`, which nothing on the development machine can read yet.
- **GTFS in the image.** Remote build uploads the local working tree, and `data/reference/gtfs/` is
  gitignored: the image has it only if the machine running `azd deploy` has it.
- **The Function collector**, if it is ever revived, still has the packaging problem it always had:
  `azd` would zip `src/nabiz/collector/` alone, `function_app.py` imports `ibb_mcp` and `nabiz` from
  outside that directory, and there is no `host.json` or `requirements.txt`. It is no longer an azd
  service in `azure.yaml`. Reviving it means solving that (a wheel built into the collector
  directory by a `prepackage` hook is the least disruptive option) — and its five timers still
  collect neither the watched lines nor the ETA log.

---

## 6. The Azure Data Explorer free cluster

ADX is **not** in the template and cannot be: the free cluster is not an ARM resource. It has no
resource provider, no subscription, and is created with a Microsoft account at
<https://dataexplorer.azure.com/freecluster>. The template takes its URI as a parameter and hands
it to the MCP server and the jobs; leaving it empty is a supported state, in which the jobs write
the lake only and the history-backed tools report `available: false` rather than guessing
(DECISIONS #1).

**Sign in with the same identity that owns the Azure subscription.** The grant below is a
cross-boundary trust: a principal from your Entra tenant being admitted to a cluster that lives
outside your subscription.

```
1. https://dataexplorer.azure.com/freecluster  ->  Create cluster
2. Create database:  nabiz
3. Paste kql/schema.kql into the query window and run each command (seven tables: create-merge,
   streaming-ingestion policy, JSON mapping). The file is generated from nabiz.collector.kusto.TABLES
   and a test fails if the two drift.
4. Admit the collector's managed identity as an ingestor:
     .add database nabiz ingestors ('aadapp=<NABIZ_COLLECTOR_CLIENT_ID>;<AZURE_TENANT_ID>')
```

Both values are printed by the `postprovision` hook in `azure.yaml`, and are outputs of the
template. The client id is the shared collector identity, so this grant survives any later change
of collector host:

```bash
azd env get-values | grep -E 'NABIZ_COLLECTOR_CLIENT_ID|AZURE_TENANT_ID'
```

Then wire it in and re-provision so the jobs pick it up:

```bash
azd env set NABIZ_KUSTO_URI https://<cluster>.<region>.kusto.windows.net
azd provision
```

`kql/dq.kql` then shows, per table, the newest row, its age and whether it is stale against the job
cadence — the quickest way to see that the jobs are feeding ADX. Verify headless ingestion before
relying on it; this is the Day-0 gate in DECISIONS #1, and the one thing in this design that might
simply be refused. If the `.add database … ingestors` command is refused, the documented fallback is
Azure SQL free with a managed identity, and DECISIONS #1 gets superseded rather than edited.

---

## 7. What it costs

Weekly, in USD, on the Azure for Students credit. Estimates from published prices, not measured
bills — replace them with Cost Management figures once the jobs have run for a week.

| Item | Weekly | Note |
|---|---|---|
| ADLS Gen2 (bronze, gzipped NDJSON) | < 0.30 | The largest writer is now the whole-fleet snapshot every 10 minutes instead of every 2 |
| **Collector jobs** (5, Consumption) | **0 – 0.79** | DECISIONS #10: 162,068 vCPU-s and 324,135 GiB-s a month on the estimate, 90 % of the free grant → $0; $3.37/month if start-up takes 40 s instead of the assumed 20. Ceiling if every execution ran to `replicaTimeout`: $34.97/month |
| Container Apps × 1 (MCP), `minReplicas: 0` | ≈ 0 | Shares the free grant with the jobs; each active hour past the grant ≈ $0.08 |
| **Container registry (Basic)** | **≈ 1.17** | ~$0.167/day, charged whether or not you push. The largest line item |
| Log Analytics + Application Insights | 0 | Inside the 5 GB/month free grant even if the 0.16 GB/day cap is hit every day (4.96 GB in a 31-day month). Every GB past the grant is $2.99 (West Europe, Azure Retail Prices API, 23 Sep 2026), so the cap is the price: at 0.5 GB/day a runaway would cost up to $31.40 in a 31-day month. Azure documents that the cap is not exact and some excess can be ingested; not measured here. The job quiets the Azure SDK's per-request logging for this reason |
| Functions Flex Consumption | 0 | Not deployed by default |
| Azure Data Explorer free cluster | 0 | Outside the subscription entirely |
| Azure Maps G2 (if enabled) | 0 | Free tile allowance is generous for a demo |
| **Total** | **≈ 1.20 – 2.30** | ≈ $5–10/month. LLM inference (PLAN §9) is separate and is the variable cost |

Container Apps prices used: $0.000034 per vCPU-second and $0.000004 per GiB-second (West Europe,
Consumption, active — Azure Retail Prices API, 23 Sep 2026); the free grant is the first 180,000
vCPU-seconds and 360,000 GiB-seconds per subscription per month
([billing](https://learn.microsoft.com/azure/container-apps/billing)). The same price list also shows
an `Environment Management Hour` meter at $0.143/hour; the billing page ties that kind of charge to
Dedicated profiles, private endpoints and planned maintenance, none of which this template uses. That
is exactly the sort of line a budget alert exists to catch.

### Budget alerts — before anything can spend

A disabled subscription is unrecoverable in a seven-day sprint. Create the alerts **before the
first `azd up`**. Three thresholds: $5 is the tripwire for a runaway job (the jobs' ceiling is
$34.97/month; the log cap's is $0 at the default 0.16 GB/day and grows by about $9.27/month for every 0.1 GB/day
above it), $20 and $40 are the sprint plan's.

**Portal** (a minute, and it does not depend on CLI versions): Cost Management + Billing → Budgets →
Add → scope: the subscription → Monthly, amount 5 → alert conditions *Actual 80 %* and *Forecasted
100 %* → your e-mail address. Repeat for 20 and 40.

**CLI**, through the ARM API directly, because the `az consumption budget` commands have changed
shape between CLI versions. The e-mail address goes on your command line only; it is not stored in
the repository:

```bash
SUB=$(az account show --query id -o tsv)
START=$(date -u +%Y-%m-01T00:00:00Z)          # a budget must start on the first of a month
EMAIL='<your e-mail address>'
for AMOUNT in 5 20 40; do
  az rest --method put \
    --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.Consumption/budgets/nabiz-monthly-$AMOUNT?api-version=2024-08-01" \
    --body "{\"properties\":{\"category\":\"Cost\",\"amount\":$AMOUNT,\"timeGrain\":\"Monthly\",
      \"timePeriod\":{\"startDate\":\"$START\"},
      \"notifications\":{
        \"actual80\":{\"enabled\":true,\"operator\":\"GreaterThanOrEqualTo\",\"threshold\":80,\"thresholdType\":\"Actual\",\"contactEmails\":[\"$EMAIL\"]},
        \"forecast100\":{\"enabled\":true,\"operator\":\"GreaterThanOrEqualTo\",\"threshold\":100,\"thresholdType\":\"Forecasted\",\"contactEmails\":[\"$EMAIL\"]}}}}"
done
az rest --method get \
  --url "https://management.azure.com/subscriptions/$SUB/providers/Microsoft.Consumption/budgets?api-version=2024-08-01" \
  --query "value[].{name:name, amount:properties.amount}" -o table
```

The request shape follows the `Microsoft.Consumption/budgets` reference (amount, `category: Cost`,
`timeGrain`, a first-of-month `startDate`, up to five notifications with a percentage threshold). It
has not been run against this subscription; if a Students subscription refuses it, use the portal.
Also check the Azure Sponsorships balance page, because Cost Management on a Students subscription
can lag by a day.

**Cheapest useful configuration.** The MCP server costs nothing idle, and the collector now lives in
its environment, so switching the Container App off (`DEPLOY_CONTAINER_APP=false`) also switches the
collector off. What is left to save is the registry: `DEPLOY_CONTAINER_REGISTRY=false` with
`MCP_CONTAINER_IMAGE` pointing at an image in a registry that allows anonymous pull. Without a local
Docker daemon that image has to be built somewhere else first, so for this sprint the registry stays.

---

## 8. Pausing and tearing down

### Pause the collector jobs

Container Apps has no switch that suspends a scheduled job (an open feature request,
microsoft/azure-container-apps#901); deleting the job stops its schedule, and the template recreates it
on the next provision. First make sure a provision
will not recreate them, then delete them:

```bash
azd env set DEPLOY_COLLECTOR_JOBS false
RG=$(azd env get-value AZURE_RESOURCE_GROUP)
for job in $(az containerapp job list -g "$RG" --query "[?starts_with(name, 'caj-')].name" -o tsv); do
  az containerapp job delete -n "$job" -g "$RG" --yes
done
az containerapp job list -g "$RG" -o table     # empty
```

Nothing collected so far is touched: the lake, the identity and its grants stay. Only now may the
laptop take over again: `make collect-supervise`.

### Resume the collector jobs

```bash
make collect-stop                       # never two collectors at once (§4.3)
azd env set DEPLOY_COLLECTOR_JOBS true
azd provision
```

### Pause everything else

The Container App already costs nothing when idle: `minReplicas: 0` means no replicas and no
billing between requests. Do **not** delete the container registry to save the $1.17/week while
the Container App or the jobs exist: every cold start and every job execution pulls the image, and
a missing registry turns into executions that cannot start.

### Tear down

```bash
azd down --force --purge
```

This deletes the resource group and everything in it — **including the lake**. Nothing here is
soft-deleted, so there is no undo. Before running it:

- Sync **`bronze/`** down (§4.5). That is where the collector writes, one gzipped NDJSON file per
  execution and source under `<source>/year=/month=/day=/hour=/`, for all seven sources. (`silver/`
  and `gold/` are created by the template but are empty.) İBB does not publish this history and
  re-collecting it takes as many days as it took the first time.
- The **ADX free cluster survives** `azd down`: it is not in the subscription. Delete it from
  <https://dataexplorer.azure.com> separately if you want it gone.
- If the collection should continue after the demo, restart the laptop collector (`make
  collect-supervise`) *after* the teardown, not before.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RequestDisallowedByPolicy` during provision | Region outside the student allowed-regions policy | Section 3; pick from the intersection |
| `The subscription is not registered to use namespace 'Microsoft.App'` | Provider not registered | Section 2; registration takes minutes |
| Hook prints `Collector: NOT deployed yet` | No image yet (first `azd up`), or `SERVICE_MCP_IMAGE_NAME` empty | §4.2, then `azd provision` |
| Job executions fail at image pull right after the first provision | The collector's AcrPull grant has not propagated through Entra yet | Wait for the next scheduled execution; check `az containerapp job execution list` |
| A job exits 1 on every execution | Every source it reads failed: the gateway refuses, or the identity cannot write `bronze/` | The `collector-job` log line names the failed reads; an `AuthorizationPermissionMismatch` on upload is the storage grant |
| `lines` logs `eta_predictions failed` | Image built without `data/reference/gtfs` | Deploy from a machine that has the GTFS export (§5) |
| MCP endpoint returns 502 right after the first provision | The placeholder image (`mcr.microsoft.com/k8se/quickstart`) listens on the wrong port | Expected until the first `azd deploy mcp`; later provisions keep the deployed image |
| Storage tools cannot see blobs | `allowSharedKeyAccess` is `false` by design | Use Entra: `az storage blob list --auth-mode login`, or Storage Explorer signed in with your account |
| Application Insights is empty | Telemetry is sent with Entra auth | Confirm the Monitoring Metrics Publisher assignment exists and `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` is set on the app. The jobs log to the console only (`ContainerAppConsoleLogs`) |
| Log Analytics stops receiving data mid-day | Daily cap hit (0.16 GB) | Find the noisy table and fix it first. Raising the cap costs up to (cap × 31 − 5) × $2.99 a month if it is hit every day — $77.74 at 1 GB/day — so raise it only with that in the budget: `azd env set NABIZ_DAILY_LOG_CAP_GB <GB>` |
| Plan creation fails on `FC1` | Only with `DEPLOY_COLLECTOR_FUNCTION=true`: region has no Flex Consumption | Section 3, or leave the Function off |

---

## How this was verified

Being precise about this matters more than sounding finished.

**23 September 2026 — the collector jobs.** Still no `az`, `azd`, `bicep` or Docker on this machine
(`which az azd bicep docker` → all missing). Done:

- `tests/test_collector_job.py` (44 tests) and the additions to `tests/test_collector.py`, offline:
  the İETT arithmetic (66 in the peak hour) recomputed from the schedule, the Bicep schedule compared
  with the Python one, the ETA log compared with the running laptop script on the same input, exit
  codes, deadlines, and the one-attempt / exact-allowance behaviour of the client against a counting
  mock transport. The collector tests also pass with the GTFS index made unavailable, as it is in CI.
- Each job run once locally against `tests/fixtures` (`NABIZ_OFFLINE=1 python -m nabiz.collector.job
  --sources …`); peak resident memory 105,906,176 bytes for `lines`, under 55 MB for the others.
- The ops branch's offline infrastructure checks, now `tests/test_infra.py` and part of the suite: 20
  passed when harvested, 21 with the log-cap check added later
  (`pytest -q tests/test_infra.py` → `21 passed`) — azd tags match `azure.yaml`, the
  container app scales to zero, no forbidden service or SKU, no `listKeys`, every module call passes
  its required parameters and no unknown ones, every module output reference resolves, array
  parameters get arrays, the parameters file covers `main.bicep` exactly, generated names fit Azure's
  limits, and both log-cap defaults fit the 5 GB/month grant when hit every day.
- `azure.yaml` parsed as YAML (Ruby's standard library), and the `postprovision` hook body executed
  under `sh` for both job states.
- The `Microsoft.App/jobs@2024-03-01` properties used were checked against the Bicep reference on
  Microsoft Learn, and the prices against the Azure Retail Prices API, both on 23 Sep.

**Not done:** `az bicep build` (CI runs it on push, not `continue-on-error`), any deployment, any image
build, any measured execution time or bill in Azure, and the Log Analytics and KQL queries in this
document and in `kql/dq.kql`, which have never met a workspace or a cluster.

What partly stands in for the compile, and where it stops. The last Bicep job on `main` (run
35767066249 on `7cc0fc1`, 22 September, Bicep CLI 0.46.1; `gh run view 35767066249 --log`) compiled
the previous `main.bicep` and its modules with warnings only (BCP318, BCP334, BCP037), including
`dailyQuotaGb: json(dailyLogCapGb)` in `modules/monitoring.bicep`. The cap's default has since changed
from `'0.5'` to `'0.16'`, a string parameter value, which the compiler never sees as a number. The new
`collectorjobs.bicep` and `collectoridentity.bicep`, and the edits to `main.bicep`, `containerapps.bicep`
and `functions.bicep`, have not been compiled by anyone; the first push reports them. On the value
itself: the Log Analytics REST specification types `dailyQuotaGb` as `number`, format `double`
(`Workspaces.json` for 2023-09-01 in Azure/azure-rest-api-specs, read 23 September), and the Microsoft
Learn template reference prints `int` only because Bicep has no float type, which is why the template
goes through `json()`. Neither says whether the service accepts a cap as small as 0.16 GB; the first
`azd provision` does. If it refuses, raise the cap with `azd env set NABIZ_DAILY_LOG_CAP_GB` and
recompute the cost row in §7 at that value.

**8 September 2026 — the first template.** A second pass over these files, with no Azure tooling,
checked the template's claims against the code and corrected three things in the first draft: the
replica ceiling defaulted to 2, which would have run two independent İETT budgets, so it now
defaults to 1; the bronze lifecycle rule was described as the place where bus number plates expire,
which is false (the plate is dropped in `BusPosition.from_fleet_raw`), and is now described as the
volume bound it is; and the Azure Maps row claimed `disableLocalAuth: true` while the module ships
`false`. A structural checker then verified balanced delimiters, module wiring, the parameters file,
no float literals and no `listKeys`-style calls across the Bicep files, and every app setting name was
diffed against the environment variables the Python reads.
