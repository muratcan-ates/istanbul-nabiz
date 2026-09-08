# Deploying İstanbul Nabız to Azure

Everything in `infra/` plus `azure.yaml` exists so that the whole system — the collector, the
lake and the MCP server — comes up with **one command**:

```bash
azd up
```

This document is the honest version of that sentence: what the template actually creates, the
two gates that have to pass before it will deploy at all on an Azure for Students subscription,
what it costs per week, what is still missing, and how to take it all down again.

> **Status, 8 September 2026 (Day 0).** The template is written and reviewed but **has never been
> deployed**, and neither `az` nor `azd` is installed on the development machine — see
> [How this was verified](#how-this-was-verified) at the bottom, which says plainly what was and
> was not checked. `azd provision` is believed complete; `azd deploy` is not, for both services:
> the collector has no `host.json` or `requirements.txt` and its imports do not survive being
> zipped on their own, and the MCP server has no `Dockerfile`. See
> [What `azd up` still needs](#what-azd-up-still-needs) — it names the exact failures rather than
> promising a green run.

---

## 1. What gets deployed

`infra/main.bicep` is deployed at **subscription scope**. It creates the resource group itself
(`rg-<environmentName>`, overridable), so `azd up` works against a subscription with nothing in
it, and `azd down` removes the group with everything inside it.

| Resource | Type · API version | Why it is here |
|---|---|---|
| Resource group | `Microsoft.Resources/resourceGroups@2024-03-01` | One group per azd environment; the unit of teardown |
| Log Analytics workspace | `Microsoft.OperationalInsights/workspaces@2023-09-01` | 30-day retention, **hard daily ingestion cap** (default 0.5 GB) |
| Application Insights | `Microsoft.Insights/components@2020-02-02` | Workspace-based; the agent → tool → model trace |
| Storage account (ADLS Gen2) | `Microsoft.Storage/storageAccounts@2023-05-01` | `isHnsEnabled: true`, Standard_LRS, **shared keys disabled**. One account for the lake *and* the Functions host — see the risk note below |
| Blob service + 4 containers | `.../blobServices@2023-05-01`, `.../containers@2023-05-01` | `bronze`, `silver`, `gold`, `deployments` |
| Lifecycle policy | `.../managementPolicies@2023-05-01` | Deletes `bronze/` after 30 days. A volume bound, **not** a privacy control — and it deletes *all* collected history, see the note below |
| Collector identity | `Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31` | Stable client id for the ADX grant; exists before the app so RBAC is not a race |
| Flex Consumption plan | `Microsoft.Web/serverfarms@2023-12-01` | `sku: { tier: FlexConsumption, name: FC1 }`, `reserved: true` |
| Function app (collector) | `Microsoft.Web/sites@2023-12-01` | `functionAppConfig`: python 3.12, `instanceMemoryMB: 512`, identity-based deployment container |
| MCP identity | `Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31` | Holds AcrPull before the first image pull |
| Container registry | `Microsoft.ContainerRegistry/registries@2023-07-01` | Basic, **no admin user**; target of azd remote build (optional — see cost) |
| Container Apps environment | `Microsoft.App/managedEnvironments@2024-03-01` | Consumption-only (no workload profiles), logs to Azure Monitor |
| Environment diagnostics | `Microsoft.Insights/diagnosticSettings@2021-05-01-preview` | Console + system logs to the workspace **without a shared key** |
| Container app (MCP server) | `Microsoft.App/containerApps@2024-03-01` | `minReplicas: 0`, **`maxReplicas: 1`**, ingress on 8000 |
| Azure Maps (optional) | `Microsoft.Maps/accounts@2023-06-01` | Gen2 / G2, `location: 'global'`, `disableLocalAuth: false` (see §3). **Off by default** |
| Role assignments | `Microsoft.Authorization/roleAssignments@2022-04-01` | Below |

> **The 30-day bronze rule is a cost bound, not a privacy control — and it is where the history
> goes.** The bus number plate never reaches this account: `BusPosition.from_fleet_raw` drops it in
> the parser, `snapshot_fleet` only ever sees parsed models, and the lake writer stores those rows
> (DECISIONS #7, and the promise in `NOTICE.md` that the plate is never written to the lake). What
> the rule *does* delete is everything the collector has ever written, because every source lands
> under `bronze/` (`NABIZ_LAKE_CONTAINER=bronze`). With no ADX cluster attached, "usually at this
> hour" can therefore never look back further than `NABIZ_BRONZE_RETENTION_DAYS`. Raise it, or
> attach ADX, before you rely on a longer window. If bronze is ever changed to hold the verbatim
> upstream body that DECISIONS #6 describes, the plate comes back with it and `NOTICE.md` has to
> be corrected *before* that change ships.

> **Unverified risk: one storage account is both the lake and the Functions host.** The account has
> `isHnsEnabled: true` for Delta's sake, and Azure Functions is *not* on Microsoft's
> [list of Azure services that support hierarchical namespace](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-supported-azure-services).
> Nothing documents the combination as forbidden, and the host only needs ordinary blob, queue and
> table calls that an HNS account serves — but this has not been deployed, so treat it as the first
> thing to check. Symptoms would be a deployment package that never appears in `deployments/` or
> timers that never fire; the fix is a second plain `StorageV2` account (`isHnsEnabled: false`) for
> the function app, leaving this one to the lake. Relatedly, Functions
> [warns against lifecycle policies](https://learn.microsoft.com/azure/azure-functions/storage-considerations#lifecycle-management-policy-considerations)
> on a function app's storage account and asks you to exclude the containers it owns
> (`azure-webjobs*`, `scm`): the rule here is scoped with `prefixMatch: ['bronze/']`, which does
> exactly that.

### Role assignments — the whole list

Nothing in this template contains a key, a connection string with a secret, or a `listKeys()`
call. Every component authenticates with a managed identity.

| Identity | Role | Scope | Why |
|---|---|---|---|
| Collector | Storage Blob Data **Owner** | storage account | The Functions host takes blob **leases** for timer singleton locks and reads its own deployment package |
| Collector | Storage Blob Data **Contributor** | storage account | The collector's own bronze/silver/gold writes — the least privilege the code needs |
| Collector | Storage **Queue** Data Contributor | storage account | Identity-based `AzureWebJobsStorage` host bookkeeping |
| Collector | Storage **Table** Data Contributor | storage account | Same |
| Collector | **Monitoring Metrics Publisher** | Application Insights | Telemetry sent with Entra auth (`APPLICATIONINSIGHTS_AUTHENTICATION_STRING`) rather than the instrumentation key |
| MCP server | AcrPull | container registry | Pull without a registry password |
| MCP server | Storage Blob Data **Reader** | storage account | Read-only: the collector writes the lake, the server only reads it |
| MCP server | Monitoring Metrics Publisher | Application Insights | Same as above |
| MCP server | Azure Maps Data Reader | Maps account | Only when `deployMaps=true`; mints browser tokens instead of embedding a subscription key |
| You (`AZURE_PRINCIPAL_ID`) | Storage Blob Data Contributor | storage account | So the collector can be run from the laptop against the real lake |

### What is deliberately *not* in the template

| Not deployed | Why |
|---|---|
| **Azure AI Search** | Basic is ~$2.42/day **even idle** — the whole student credit in six weeks. There is no retrieval layer in this design: every tool is parametric (DECISIONS #2) |
| **Stream Analytics** | No free tier at all; the timer-driven collector does the same job for cents |
| **Data Factory** | Data flows bill per vCore-hour |
| Anything from **Marketplace** | Bills outside the Azure credit and can charge a card directly |
| **Azure Data Explorer** | The free cluster has **no ARM resource provider** — it cannot be expressed in Bicep. Created by hand, see [section 6](#6-the-azure-data-explorer-free-cluster) |
| **Key Vault** | Nothing to put in it. Adding one would mean inventing a secret |

---

## 2. Prerequisites

```bash
brew install azure-cli
brew install azd                       # or: curl -fsSL https://aka.ms/install-azd.sh | bash
az version && azd version
```

You do **not** need Docker. `azure.yaml` sets `remoteBuild: true`, so the MCP image is built
inside Azure Container Registry — which also sidesteps the M1/arm64 vs linux/amd64 problem.

```bash
az login
az account show -o table               # confirm the Azure for Students subscription is Enabled
```

Register the resource providers once per subscription (each takes a few minutes, and an
unregistered provider fails at *deploy* time, not at plan time):

```bash
for p in Microsoft.Resources Microsoft.Storage Microsoft.Web Microsoft.App \
         Microsoft.ContainerRegistry Microsoft.OperationalInsights Microsoft.Insights \
         Microsoft.ManagedIdentity Microsoft.Maps; do
  az provider register -n $p
done
az provider list --query "[?registrationState!='Registered' && contains('Microsoft.App Microsoft.Web Microsoft.Storage Microsoft.ContainerRegistry Microsoft.Maps', namespace)].{ns:namespace, state:registrationState}" -o table
```

`scripts/probe_day0.py --azure` reports provider state as check **A4** and never registers
anything itself.

---

## 3. The Day-0 region gate

Two constraints have to be satisfied by a single region, and neither is visible in the portal
by default:

1. **Azure for Students carries a hidden "Allowed resource deployment regions" policy.** It
   typically permits about five regions, and *the list differs per subscription*. A region
   outside it fails the deployment with `RequestDisallowedByPolicy`.
2. **Functions Flex Consumption is not available everywhere.** A region outside its list fails
   with a plan creation error.

Compute the intersection before choosing `location`:

```bash
# What region policies exist at all (read the display names — the built-in is "Allowed locations")
az policy assignment list --query "[].{name:displayName, definition:policyDefinitionId}" -o table

# (a) regions the policy allows, normalised to short names
az policy assignment list --query "[].parameters.listOfAllowedLocations.value[]" -o tsv \
  | tr -d ' ' | tr '[:upper:]' '[:lower:]' | sort -u > /tmp/allowed.txt

# (b) regions that support Functions Flex Consumption (returns display names — same normalisation)
az functionapp list-flexconsumption-locations --query "[].name" -o tsv \
  | tr -d ' ' | tr '[:upper:]' '[:lower:]' | sort -u > /tmp/flex.txt

# (c) pick from the intersection
comm -12 /tmp/allowed.txt /tmp/flex.txt
```

Both normalisations are idempotent: policy parameters usually hold short names (`westeurope`)
already and the Functions command returns display names (`West Europe`), and the pipeline turns
either into the same thing.

If `/tmp/allowed.txt` comes back empty there is **no** region policy on the subscription and any
Flex region will do — but confirm that rather than assume it, because the failure mode arrives
half way through `azd up`, after the resource group already exists.

If the intersection is empty, the options in order of preference are: request a policy exemption;
move the collector to Linux Consumption (Y1) in an allowed region, which means changing the SKU
in `infra/modules/functions.bicep` and dropping `functionAppConfig`; or run the collector locally
and deploy only the MCP server.

`scripts/probe_day0.py --azure` runs exactly this intersection as checks **A2** and **A3** and
prints the surviving regions.

Azure Maps is a separate gate: it is `location: 'global'`, so the region policy either permits
`Microsoft.Maps` or it does not. That is why `deployMaps` defaults to **false** — a Maps refusal
must not take the rest of the deployment down with it. Turn it on deliberately:

```bash
azd env set DEPLOY_MAPS true && azd provision
```

The account keeps **subscription keys enabled** (`disableLocalAuth: false`), because
`src/nabiz/web/main.py` reads `NABIZ_MAPS_KEY` today. The template never emits that key — fetch it
deliberately when you need it, and set it as an app setting yourself:

```bash
az maps account keys list -n <maps-account> -g $(azd env get-value AZURE_RESOURCE_GROUP) \
  --query primaryKey -o tsv
```

The better path is already provisioned alongside it: the Container App identity holds **Azure Maps
Data Reader**, so once the web layer mints a short-lived Entra token server-side and the map uses
`authType: 'anonymous'`, pass `disableLocalAuth: true` to the module and no key exists at all.

---

## 4. `azd up`

```bash
cd /path/to/istanbul-nabiz
azd auth login
azd env new nabiz-dev                 # environment name -> rg-nabiz-dev, and the azd-env-name tag
azd env set AZURE_LOCATION westeurope # a region from the intersection in section 3
azd up
```

`azd up` provisions `infra/main.bicep` and then deploys both services. It matches each service in
`azure.yaml` to its Azure resource by the `azd-service-name` tag set in Bicep:

| `azure.yaml` service | Source | Target resource |
|---|---|---|
| `collector` | `src/nabiz/collector` | `Microsoft.Web/sites` tagged `azd-service-name: collector` |
| `mcp` | repo root + `Dockerfile` | `Microsoft.App/containerApps` tagged `azd-service-name: mcp` |

### Knobs

Every parameter in `infra/main.parameters.json` reads an azd environment variable, so nothing
needs editing to change behaviour:

| `azd env set …` | Default | Effect |
|---|---|---|
| `DEPLOY_CONTAINER_APP` | `true` | `false` skips the Container App, its environment and the registry entirely |
| `DEPLOY_CONTAINER_REGISTRY` | `true` | `false` keeps the Container App but drops the ~$1.17/week registry; you must then set `MCP_CONTAINER_IMAGE` |
| `MCP_CONTAINER_IMAGE` | *(empty)* | Pin a public image, e.g. `ghcr.io/<you>/ibb-mcp:0.1.0` |
| `DEPLOY_MAPS` | `false` | `true` adds the Azure Maps G2 account |
| `NABIZ_KUSTO_URI` | *(empty)* | ADX free cluster URI; empty is a valid state |
| `NABIZ_KUSTO_DB` | `nabiz` | ADX database |
| `NABIZ_BRONZE_RETENTION_DAYS` | `30` | Lifecycle deletion age for raw bronze |
| `NABIZ_MCP_MAX_REPLICAS` | `1` | Replica ceiling — see the warning below |
| `NABIZ_DAILY_LOG_CAP_GB` | `0.5` | Log Analytics daily ingestion cap |
| `NABIZ_RESOURCE_GROUP` | *(empty)* | Override the `rg-<env>` name |

> **Do not raise `NABIZ_MCP_MAX_REPLICAS` above 1.** The İETT hourly budget and the TTL cache
> live *in process* (`ibb_mcp.http.PoliteClient`: `HourlyBudget("iett", limit=80)` and a 6 s gate
> on `api.ibb.gov.tr`). Two replicas are two independent budgets — up to **160 requests/hour**
> against a service documented at 100, and a gateway that this project promises to call every 6 s
> getting hit every 3, which is the pattern that produces 503s after ~15 rapid calls. It also
> gives two callers two different answers to "how old is this data". Scaling out needs a shared
> cache and a shared budget first; the default is therefore 1, not 2.

> **azd substitutes `${VAR}` as text.** Boolean and numeric parameters must be spelled exactly
> `true` / `false` / `30` — `True`, `yes` or `"true"` will fail ARM's type check with a message
> that does not mention azd.

---

## 5. What `azd up` still needs

This is the part that is not finished. `azd provision` works on its own; `azd deploy` does not
yet, because neither service has its packaging files. Both are owned by other days of the sprint.

### 5.1 Collector — `src/nabiz/collector/` — **blocked on packaging**

`function_app.py`, `snapshots.py`, `lake.py` and `kusto.py` all exist and the timers are
written. What is missing is the two files the Functions host needs, plus a real structural
problem that has to be decided before `azd deploy collector` can work at all.

**The problem.** `azd deploy collector` zips **`src/nabiz/collector/` and nothing else**, and the
Functions host imports `function_app.py` from the root of that zip. But `function_app.py` imports
absolute package paths that are not inside it:

```python
from ibb_mcp.config import Settings            # lives in src/ibb_mcp/
from nabiz.collector.kusto import KustoSink    # lives one directory up
```

Deployed as-is this fails at host start with `ModuleNotFoundError: No module named 'ibb_mcp'`,
which reads like a dependency problem and is really a layout problem. Three ways out, in order of
how little they disturb the code:

1. **Ship the project as a wheel** (recommended). Build it into the collector directory at
   package time and reference it from `requirements.txt`:

   ```
   # src/nabiz/collector/requirements.txt
   azure-functions>=1.21
   ./istanbul_nabiz-0.1.0-py3-none-any.whl
   httpx>=0.27
   pydantic>=2.7
   azure-identity>=1.17
   azure-kusto-data>=4.5
   azure-kusto-ingest>=4.5
   deltalake>=0.19
   pyarrow>=16
   ```

   built by a service-scoped azd hook in `azure.yaml`
   (`uv build --wheel --out-dir src/nabiz/collector .` under `services.collector.hooks.prepackage`).
   Both packages then install normally and every import resolves.
2. **Vendor at package time** — a `prepackage` hook that copies `src/ibb_mcp` and `src/nabiz`
   into the collector directory. Fewer moving parts, but two copies of the source exist during a
   deploy and one of them is easy to edit by mistake.
3. **Move `function_app.py` to a directory that contains both packages** and repoint
   `azure.yaml`. Cleanest import story, largest diff.

This is a decision for whoever owns the collector, not something the infrastructure should settle
silently — so `azure.yaml` still points at `src/nabiz/collector` and this section is the note
saying why that is not yet enough.

**Also still missing:** `host.json` (`{"version": "2.0", "logging": {...}}`) and the
`requirements.txt` above. Neither exists, so packaging fails before it reaches the import problem.

**App settings the template already provides.** These are set on the function app by
`infra/modules/functions.bicep` and use exactly the names the collector's own code reads
(`nabiz/collector/lake.py`, `nabiz/collector/kusto.py`):

| Setting | Value | Read by |
|---|---|---|
| `AZURE_STORAGE_ACCOUNT` | storage account name | `lake.ENV_ACCOUNT` — its presence is what switches the lake writer from `data/lake` to Azure |
| `NABIZ_LAKE_CONTAINER` | `bronze` | `lake.ENV_CONTAINER` |
| `NABIZ_KUSTO_URI` | ADX URI, may be empty | `kusto.ENV_URI` |
| `NABIZ_KUSTO_DB` | `nabiz` | `kusto.ENV_DATABASE` |
| `NABIZ_KUSTO_MI_CLIENT_ID` | collector identity client id | `kusto.ENV_MI_CLIENT_ID` — a *user-assigned* identity cannot be inferred, it has to be named |
| `AZURE_CLIENT_ID` | same client id | `DefaultAzureCredential`, for the lake writer |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | — | the Functions host |
| `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` | `ClientId=…;Authorization=AAD` | sends telemetry with the identity, not the instrumentation key |
| `AzureWebJobsStorage__accountName` / `__credential` / `__clientId` | — | identity-based host storage; there is no connection string |

`AZURE_STORAGE_CONNECTION_STRING` is deliberately **not** set: that code path needs an account
key, and the storage account has shared-key access disabled.

**Timer schedules.** The template also sets `NABIZ_SCHEDULE_ISPARK`, `NABIZ_SCHEDULE_IETT_FLEET`,
`NABIZ_SCHEDULE_METRO`, `NABIZ_SCHEDULE_TRAFFIC` and `NABIZ_SCHEDULE_AIR_QUALITY` to
`0 */10 * * * *`, `0 */2 * * * *`, `0 5 * * * *`, `0 10 * * * *` and `0 15 * * * *` — the same
five values `function_app.py` currently hard-codes. They are **inert** until a trigger reads one,
which is a one-character-per-line change:

```python
@app.timer_trigger(schedule="%NABIZ_SCHEDULE_ISPARK%", ...)
```

After that, slowing the collector down when the İBB gateway complains is
`azd env set NABIZ_SCHEDULE_ISPARK '0 0 * * * *' && azd provision`, not a redeploy.

### 5.2 MCP server — `Dockerfile` at the repository root (Day 3)

`azure.yaml` points the `mcp` service at `./Dockerfile` with the repository root as build context.
The file does not exist yet. This is what it needs to be:

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY data/reference/ ./data/reference/
RUN pip install --no-cache-dir .

ENV NABIZ_GTFS_DIR=/app/data/reference/gtfs \
    NABIZ_PLACES_CSV=/app/data/reference/places.csv \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# The port must stay 8000: it is the containerApp ingress targetPort in
# infra/modules/containerapps.bicep.
CMD ["ibb-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
```

Two things to know before the first build:

- `data/reference/gtfs/` is **gitignored** (26 MB of `stop_times.csv` and the built
  `route_sequences.json.gz`). Remote build uploads the local working tree, so the image is only
  complete if those files are present locally. A CI build has to fetch or rebuild them first.
- Add a `.dockerignore` for `.venv/`, `.git/`, `tests/fixtures/`, `data/lake/` — otherwise the
  remote build uploads hundreds of megabytes on every deploy.

Until both exist, use `azd provision` (infrastructure only) rather than `azd up`.

---

## 6. The Azure Data Explorer free cluster

ADX is **not** in the template and cannot be: the free cluster is not an ARM resource. It has no
resource provider, no subscription, and is created with a Microsoft account at
<https://dataexplorer.azure.com/freecluster>. The template takes its URI as a parameter and hands
it to both services as an app setting; leaving it empty is a supported state, in which the
history-backed tools (`ispark_typical_occupancy`, `air_quality_forecast`) report
`available: false` rather than guessing (DECISIONS #1).

**Sign in with the same identity that owns the Azure subscription.** The grant below is a
cross-boundary trust: a principal from your Entra tenant being admitted to a cluster that lives
outside your subscription.

```
1. https://dataexplorer.azure.com/freecluster  ->  Create cluster
2. Create database:  nabiz
3. Create the tables (kql/schema.kql, Day 1), then enable streaming ingestion per table:
     .alter table ispark_snapshot policy streamingingestion enable
4. Admit the collector's managed identity as an ingestor:
     .add database nabiz ingestors ('aadapp=<NABIZ_COLLECTOR_CLIENT_ID>;<AZURE_TENANT_ID>')
```

Both values are printed by the `postprovision` hook in `azure.yaml`, and are outputs of the
template:

```bash
azd env get-values | grep -E 'NABIZ_COLLECTOR_CLIENT_ID|AZURE_TENANT_ID'
```

Then wire it in and re-provision so the app settings pick it up:

```bash
azd env set NABIZ_KUSTO_URI https://<cluster>.<region>.kusto.windows.net
azd provision
```

Verify headless ingestion actually works *before* relying on it — this is the Day-0 gate in
DECISIONS #1, and it is the one thing in this design that might simply be refused:

```bash
.venv/bin/python - <<'EOF'
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
import os
kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(os.environ["NABIZ_KUSTO_URI"])
print(KustoClient(kcsb).execute("nabiz", ".show database principals").primary_results[0])
EOF
```

If the `.add database … ingestors` command is refused, the documented fallback is Azure SQL free
with a managed identity, and DECISIONS #1 gets superseded rather than edited.

---

## 7. What it costs

Weekly, in USD, on the Azure for Students credit. These are estimates from published list prices,
not measured bills — replace them with real numbers from Cost Management once the collector has
run for a week.

| Item | Weekly | Note |
|---|---|---|
| ADLS Gen2 (bronze gzipped + Delta) | < 0.30 | The İETT fleet response is 1.1 MB every 2 min ≈ 5.5 GB/week raw; gzip and the 30-day lifecycle rule keep it bounded |
| Functions Flex Consumption, 512 MB | ≈ 0.30 | ~6,000 short executions/week; the free grant may cover it entirely |
| Container Apps × 1, `minReplicas: 0` | 0 | Inside the monthly free grant (180k vCPU-s / 360k GiB-s / 2M requests) |
| **Container registry (Basic)** | **≈ 1.17** | ~$0.167/day, charged whether or not you push. The largest line item |
| Log Analytics + Application Insights | 0 | Under the 5 GB/month free grant, enforced by the daily cap |
| Azure Data Explorer free cluster | 0 | Outside the subscription entirely |
| Azure Maps G2 (if enabled) | 0 | Free tile allowance is generous for a demo |
| **Total** | **≈ 1.80** | ≈ $7–8/month. LLM inference (PLAN §9) is separate and is the variable cost |

Set budgets before the first deploy — a disabled subscription is unrecoverable in a seven-day
sprint. Set two budgets with alerts — $20 and $40 — under **Cost Management + Billing → Budgets** in the
portal. (`az consumption budget` can do it from the CLI, but its arguments have shifted between
CLI versions; the portal takes a minute and does not lie about which version you are on.) Also
check the Azure Sponsorships balance page, because Cost Management on a Students subscription can
lag by a day.

**Cheapest useful configuration** — collector plus lake only, no registry, no Container App
(the MCP server still runs locally over stdio for VS Code Copilot and Claude, which is how it is
used in most of the demo anyway):

```bash
azd env set DEPLOY_CONTAINER_APP false
azd provision
```

That is roughly **$0.60/week**.

---

## 8. Pausing and tearing down

### Pause without deleting

The Container App already costs nothing when idle: `minReplicas: 0` means no replicas and no
billing between requests. The collector is what keeps spending, and what keeps calling İBB.

```bash
# Stop collecting, keep everything and all the data collected so far
az functionapp stop -n $(azd env get-value SERVICE_COLLECTOR_NAME) -g $(azd env get-value AZURE_RESOURCE_GROUP)

# Or slow it down instead of stopping it (İSPARK hourly rather than every 10 minutes)
azd env set NABIZ_SCHEDULE_ISPARK '0 0 * * * *' && azd provision

# Resume
az functionapp start -n $(azd env get-value SERVICE_COLLECTOR_NAME) -g $(azd env get-value AZURE_RESOURCE_GROUP)
```

Do **not** delete the container registry to save the $1.17 while the Container App is still
deployed: the app pulls its image again on every cold start from zero replicas, and a missing
registry turns into a revision that will not start.

### Tear down

```bash
azd down --force --purge
```

This deletes the resource group and everything in it — **including the lake**. Nothing here is
soft-deleted, so there is no undo. Before running it:

- Copy anything you want to keep out of **`bronze/`** — that is where the collector actually
  writes, one gzipped NDJSON file per timer tick under `<source>/year=/month=/day=/hour=/`, for
  all five sources. (`silver/` and `gold/` are created by the template but are empty until the
  Delta writer in `nabiz.collector.lake` learns to target ADLS rather than the local filesystem.)
  İBB does not publish this history and re-collecting it takes as many days as it took the first
  time.
- The **ADX free cluster survives** `azd down`: it is not in the subscription. Delete it from
  <https://dataexplorer.azure.com> separately if you want it gone.
- Per PLAN §11 Day 6, the intended end state after the demo is to `azd down` the paid pieces and
  keep the collector, the lake and the free cluster running so the history keeps growing.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RequestDisallowedByPolicy` during provision | Region outside the student allowed-regions policy | Section 3; pick from the intersection |
| Plan creation fails on `FC1` | Region has no Flex Consumption | Section 3, or fall back to Y1 Linux Consumption |
| `The subscription is not registered to use namespace 'Microsoft.App'` | Provider not registered | Section 2; registration takes minutes |
| Function deploy fails with 403 reading the deployment container | Entra role propagation | The template already orders the role assignments before the site via `dependsOn`; if it still happens, wait a minute and `azd deploy collector` again |
| MCP endpoint returns 502 right after provision | The placeholder image (`mcr.microsoft.com/k8se/quickstart`) is running and listens on the wrong port | Expected before the first `azd deploy mcp` |
| `azd deploy mcp` fails: no Dockerfile | Section 5.2 | Use `azd provision` until it exists |
| Storage tools cannot see blobs | `allowSharedKeyAccess` is `false` by design | Use Entra: `az storage blob list --auth-mode login`, or Storage Explorer signed in with your account |
| Collector deploys but the package never lands in `deployments/`, or timers never fire | Possibly the hierarchical namespace on the shared storage account (see §1) — unverified | Create a plain `StorageV2` account (`isHnsEnabled: false`) and point `functionAppConfig.deployment.storage` and `AzureWebJobsStorage__accountName` at it; keep the lake on the HNS account |
| Application Insights is empty | Telemetry is sent with Entra auth | Confirm the Monitoring Metrics Publisher assignment exists and `APPLICATIONINSIGHTS_AUTHENTICATION_STRING` is set on the app |
| Log Analytics stops receiving data mid-day | Daily cap hit (0.5 GB) | Find the noisy table, then raise it deliberately: `azd env set NABIZ_DAILY_LOG_CAP_GB 1` |

---

## How this was verified

Being precise about this matters more than sounding finished.

**Reviewed, 8 September 2026.** A second pass over these files (still with no `az`, `azd` or
`bicep` on the machine) checked the template's claims against the code rather than against
itself, and corrected three things that were wrong in the first draft: the replica ceiling
defaulted to 2, which would have run two independent İETT budgets — 160 requests/hour against a
documented 100 — so it now defaults to 1; the bronze lifecycle rule was described as the place
where bus number plates expire, which is false for the collector as written (the plate is dropped
in `BusPosition.from_fleet_raw` and the lake only ever receives parsed rows, exactly as `NOTICE.md`
promises) and is now described as the volume bound it is; and the Azure Maps row above claimed
`disableLocalAuth: true` while the module ships `false`. The hierarchical-namespace risk in §1 was
not identified in the first draft at all.

**Not done.** `az bicep build --file infra/main.bicep --stdout` was **not run**: neither the Azure
CLI nor the Bicep CLI is installed on this machine (`which az azd bicep` → all missing; this is
also recorded as checks T3/T4 in `docs/day0_report.json`). No Azure resource was created and
`azd up` was never invoked. The compile does run in CI — `.github/workflows/ci.yml` has a `bicep`
job that installs Bicep and runs exactly that command — so the first push is the real compiler
check, and it is not marked `continue-on-error`. The template is therefore **unproven against a real compiler and a
real subscription** — running `az bicep build` is the first thing to do once the CLI is installed,
and it is expected to emit `BCP318` warnings where outputs of the conditional `containerapps` and
`maps` modules are read behind a ternary. Warnings, not errors.

**Done.** Line-by-line review against the resource types and API versions listed in section 1,
plus a structural checker written for this repository that verifies, across all six `.bicep`
files: balanced delimiters outside strings and comments; that every `module` path resolves; that
every module call passes each of the module's required parameters and no unknown ones; that every
`x.outputs.y` reference names a real output; that `main.parameters.json` covers every required
parameter of `main.bicep` and invents none; that no symbol is declared twice; that no float
literal is used (Bicep has no float type — hence `json('0.5')`); and that no `listKeys` /
`listAccountSas` / `listServiceSas` call appears anywhere, which is what makes "no keys in the
template" a checked property rather than an intention. It reports:

```
scanned 6 bicep files: main.bicep, containerapps.bicep, functions.bicep, maps.bicep, monitoring.bicep, storage.bicep

PASS — structure, module wiring and parameter file are consistent
```

`azure.yaml` was parsed as YAML, and the `postprovision` hook body was extracted and executed
under `sh` with representative values to confirm it is valid shell and prints the ADX grant
command correctly.

Finally, every app-setting name the template writes was diffed against every environment variable
name the Python actually reads (`os.getenv`, `os.environ[...]` and the `ENV_*` constants in
`nabiz/collector/lake.py` and `nabiz/collector/kusto.py`). Nothing the code needs in Azure is
unset, and everything set is either read by the code, read by the Azure platform
(`AzureWebJobsStorage__*`, `APPLICATIONINSIGHTS_*`, `AZURE_CLIENT_ID`), or the five
`NABIZ_SCHEDULE_*` settings that are documented above as inert. The names that the code reads but
the template does not set are all deliberate: `AZURE_STORAGE_CONNECTION_STRING` needs a key,
`NABIZ_MAPS_KEY` / `NABIZ_HOST` / `NABIZ_PORT` / `NABIZ_CORS_ORIGINS` belong to the web service
that is not deployed yet, and the rest (`NABIZ_OFFLINE`, `NABIZ_RADIUS_KM`, `NABIZ_MAX_RESULTS`,
`NABIZ_FIXTURES_DIR`, `NABIZ_LAKE_DIR`, `NABIZ_LAKE_FORMAT`, `NABIZ_KUSTO_AUTH`) have working
defaults.
