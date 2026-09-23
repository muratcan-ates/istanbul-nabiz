# Architecture decision record

Each entry records a decision that would be expensive to reverse, the situation that forced it, and what
it costs. Decisions are not deleted when they turn out badly — they are superseded by a later entry, so
the reasoning stays readable.

| # | Decision | Status |
|---|---|---|
| [1](#1-azure-data-explorer-free-cluster-for-history-not-fabric-eventhouse-or-azure-sql) | Azure Data Explorer free cluster for history, not Fabric Eventhouse or Azure SQL | Accepted — **gated** on headless ingestion auth |
| [2](#2-the-mcp-server-is-the-product-the-agent-is-its-first-client) | The MCP server is the product; the agent is its first client | Accepted |
| [3](#3-one-shared-collector-and-a-ttl-cache-never-a-per-user-upstream-call) | One shared collector and a TTL cache, never a per-user upstream call | Accepted — the collector's host is now #10 |
| [4](#4-bus-eta-from-stop-sequence-and-distance-not-machine-learning) | Bus ETA from stop sequence and distance, not machine learning | Accepted |
| [5](#5-the-llm-is-swappable-through-environment-variables) | The LLM is swappable through environment variables | Accepted |
| [6](#6-delta-lake-for-silver-and-gold-rather-than-plain-parquet) | Delta Lake for silver and gold rather than plain Parquet | Accepted |
| [7](#7-bus-number-plates-are-dropped-at-the-parsing-boundary) | Bus number plates are dropped at the parsing boundary | Accepted |
| [8](#8-src-layout-with-two-packages-instead-of-the-packages-layout-in-planmd) | `src/` layout with two packages instead of the `packages/` layout in PLAN.md | Accepted — supersedes PLAN.md §12; its import rule is enforced since #19 |
| [9](#9-pivot-from-nefes-air-quality-early-warning-to-nabız-city-agent) | Pivot from "Nefes" (air-quality early warning) to "Nabız" (city agent) | Accepted |
| [10](#10-the-collector-runs-as-scheduled-container-apps-jobs-not-on-the-laptop-or-functions-timers) | The collector runs as scheduled Container Apps Jobs, not on the laptop or Functions timers | Accepted — not yet deployed |
| [11](#11-one-container-image-for-the-mcp-server-and-the-collector-harvested-from-the-ops-branch) | One container image for the MCP server and the collector, harvested from the ops branch | Accepted — not yet built |
| [12](#12-provisioning-takes-the-deployed-image-as-an-input-and-never-deploys-a-job-with-a-placeholder) | Provisioning takes the deployed image as an input, and never deploys a job with a placeholder | Accepted |
| [13](#13-alerts-are-evaluated-statelessly-the-client-holds-the-subscription-and-the-cooldown) | Alerts are evaluated statelessly; the client holds the subscription and the cooldown | Accepted |
| [14](#14-compare-travel-modes-over-a-distance-justified-rail-graph-do-not-plan-routes) | Compare travel modes over a distance-justified rail graph; do not plan routes | Accepted — narrows PLAN.md §17 for the comparison slice |
| [15](#15-harden-the-public-mcp-endpoint-stateless-transport-per-tool-token-buckets-optional-key-closed-cors) | Harden the public MCP endpoint: stateless transport, per-tool token buckets, optional key, closed CORS | Accepted — not yet deployed |
| [16](#16-every-span-goes-through-one-allow-list-no-auto-instrumentation) | Every span goes through one allow-list; no auto-instrumentation | Accepted — not yet deployed; the module is `ibb_mcp.telemetry` since #19 |
| [17](#17-tests-and-ci-read-only-committed-scrubbed-data) | Tests and CI read only committed, scrubbed data | Accepted |
| [18](#18-serve-the-arrival-estimator-with-the-better-held-out-score-the-untuned-rate) | Serve the arrival estimator with the better held-out score: the untuned rate | Accepted — supersedes the tool's use of the calibrated profile |
| [19](#19-the-server-package-imports-nothing-from-the-apps-and-code-size-is-ratcheted) | The server package imports nothing from the apps, and code size is ratcheted | Accepted |

---

## 1. Azure Data Explorer free cluster for history, not Fabric Eventhouse or Azure SQL

**Date:** 2026-09-08 · **Status:** Accepted, gated on the Day-0 headless-auth check

### Context

The whole "usually at this hour" and "measured ETA error" story needs a time-series store that İBB does
not provide, filled by a collector that writes every 2–10 minutes. Three candidates:

- **Microsoft Fabric Eventhouse** — the keyword-richest option, but the Fabric trial is tied to a school
  tenant, does not open on a personal account, and the trial ships without Copilot / Data Agent. Anything
  that depends on a tenant policy I do not control cannot sit on the critical path of a seven-day sprint.
- **Azure SQL free offer** — reliable and familiar, but a row store queried with SQL over a few million
  timestamped snapshots is the wrong shape, and it consumes subscription quota that the rest of the
  deployment needs.
- **Azure Data Explorer free cluster** — no subscription required, roughly 100 GB, KQL, streaming
  ingestion, and *the same engine as Eventhouse*. It costs nothing against the Azure for Students credit,
  which is the scarce resource here.

### Decision

Use the **ADX free cluster** (database `nabiz`) as the analytics store, with the table names from
PLAN.md §4.2 and `arg_max` materialised views for "latest state". Azure SQL free stays the documented
fallback.

The decision carries an explicit **gate**, checked on Day 0: the free cluster must accept a *headless*
ingestion principal so the collector Function can write unattended —
`.add database nabiz ingestors ('aadapp=<clientId>;<tenantId>')`. If the tenant forbids app registration,
or the free cluster refuses the principal, the fallback is Azure SQL free with a managed identity, and
this entry is superseded rather than edited.

### Consequences

- Zero cost and no dependency on the student subscription's quota for the analytics layer.
- KQL is the one genuinely new technology in the stack; it is also the Eventhouse query language, so the
  Fabric mirror on the roadmap is a migration rather than a rewrite.
- **No SLA, and it can be reclaimed.** The history store therefore must never be on the critical path of a
  live answer: `analytics.HistoryStore` reports itself unavailable and the affected tools
  (`ispark_typical_occupancy`, `air_quality_forecast`) return `available: false` with an explanation
  instead of failing or guessing. Live tools keep working with the store completely absent.
  *(2026-09-23: `HistoryStore` was a stub that never read a store, and it is removed.
  `ispark_typical_occupancy` reads the committed profile through `ibb_mcp.occupancy`, and
  `air_quality_forecast` reads 48 hours of İBB's own history, so neither depends on ADX today.)*
- The free cluster's terms do not allow personal data, which reinforces decision 7.
- Portability is bought separately, by writing Delta first and ingesting into ADX second (decision 6).

---

## 2. The MCP server is the product; the agent is its first client

**Date:** 2026-09-08 · **Status:** Accepted

### Context

The obvious build is a chat UI that calls İBB directly — one codebase, one demo, done in two days. But a
chat UI is a demo, and the prior art on GitHub for this data is a handful of GeoJSON converters. What is
actually missing from the İBB ecosystem is not another app; it is an integration layer. A second
consideration is verifiability: if the agent can reach the data by any path other than a typed tool, there
is no way to check that a number in an answer came from anywhere real.

### Decision

`ibb_mcp` is a standalone MCP server and the only way into İBB data. Every capability is a **parametric,
typed tool** returning a `ToolResult` with a provenance stamp. There is no free-form query tool, no
NL-to-KQL and no NL-to-SQL path — a tool the model can shape arbitrarily produces output nobody can
verify. The Nabız agent in `src/nabiz/agent/` is one MCP client among several; VS Code Copilot, Claude and
Copilot Studio are the others, and they get exactly the same tools with no privileged path for our own
agent.

### Consequences

- The provenance envelope becomes mandatory, which is what makes the numeric-faithfulness check in the
  eval harness possible at all: every number in an answer must appear in a tool result.
- More work than a monolith — a server, a transport, hosting, and a tool contract that cannot casually
  change. Contract tests against recorded fixtures are the price of that stability.
- It gives the demo its strongest moment: the same server answering inside VS Code Copilot, with no
  Nabız-specific code in the client.
- The server can be published and adopted independently of everything Azure-specific in this repo
  (decision 8).

---

## 3. One shared collector and a TTL cache, never a per-user upstream call

**Date:** 2026-09-08 · **Status:** Accepted

### Context

Two hard facts about the upstream, both verified rather than assumed:

- The İETT web-service document specifies **100 requests per hour** for the fleet/position service.
- `api.ibb.gov.tr` is a single gateway in front of *every* İBB service, and it starts returning HTTP 503
  to all of them after roughly fifteen rapid requests.

A conventional "one upstream call per user question" design would therefore exhaust the İETT budget with
a hundred questions, and could take the gateway down for every other consumer of this public data, not
just for us. These are shared public services with no registration and no quota to buy.

### Decision

Nothing reaches İBB on a user's behalf. Requests go through one shared `PoliteClient` (`src/ibb_mcp/http.py`)
that enforces a **minimum 6-second interval per host**, a **sliding hourly budget of 80** for İETT — under
İBB's 100, so we stop before they do — and exponential backoff with jitter on the retryable statuses. All
reads then go through `TTLCache` (`src/ibb_mcp/cache.py`), which adds:

- **single flight** — fifty simultaneous "parking near Taksim" questions produce one upstream request and
  forty-nine waiters;
- **stale-on-error** — when the gateway 503s, an expired entry is returned and marked `cached`, so the
  answer says "veri X dakika önceki" instead of failing or inventing a value;
- **counters** — hits, misses, stale reads and last error per source, which is exactly what the
  `city_freshness` tool and the daily data-quality report publish.

Time-to-live is set per source from how fast the upstream really moves, not uniformly: İSPARK 5 min, İETT
line positions 60 s, fleet 2 min, metro status 5 min, metro stations and timetables 1 day, traffic 5 min,
air-quality readings 30 min.

### Consequences

- An answer can be up to one TTL old — accepted, because the age is always stated.
- A gateway outage degrades answers instead of breaking them.
- The MCP server keeps state in process, so scaling out multiplies the budget by the replica count: the
  Container App runs with a low replica ceiling, and the heavy periodic reading is done by the single
  collector Function, not by the server.
- The test suite must never touch the network. `tests/conftest.py` bolts the client to a mock transport
  that raises, so a stray live call fails loudly rather than quietly consuming the shared budget.

---

## 4. Bus ETA from stop sequence and distance, not machine learning

**Date:** 2026-09-08 · **Status:** Accepted

### Context

İETT publishes live vehicle positions and a planned timetable, but no arrival prediction — journey J2
needs one. The tempting answer is a model. On day one there is no arrival history to train on (that is
precisely what this project starts collecting), and a model would take days to be worth anything. More
importantly, a wrong minute the user cannot interrogate is worse than a rough minute they can.

### Decision

Explainable arithmetic, in `src/ibb_mcp/eta.py`, with three methods tried in order of preference and the
method **always recorded on the result** so the agent can say how a number was derived:

1. **`stop_sequence`** — the bus reports the stop it is nearest to (`yakinDurakKodu`), which joins to GTFS
   `stops.stop_code` (verified 31/31 on line 500T). When that stop and the target both sit on the route's
   ordered stop list and the bus is before the target, the gap is how many stops away it is, multiplied by
   a per-route seconds-per-stop figure. This follows the road the bus actually drives.
2. **`distance`** — no usable stop order. Great-circle distance inflated by a road-winding factor over an
   assumed city speed derived from the live fleet. It cannot see direction of travel, one-way streets or
   the Bosphorus, so it never earns better than `medium` confidence.
3. **`schedule`** — no live vehicle approaching. Fall back to today's planned *departures*: "there is a
   500T booked for 14:40" — not "a bus reaches your stop at 14:40". Confidence `low`.

Every estimate is written to `eta_log` with its method and inputs. The collector later marks the vehicle's
real arrival (that door number appearing with the target stop as its `yakinDurakKodu`), turning the log
into a measured error.

### Consequences

- Users and reviewers can follow the arithmetic; the `diagnostics` returned beside each arrival is
  JSON-serialisable precisely so it can be logged and audited.
- The constants in `EtaParams` are moved by the measured MAE, not by intuition.
- The method degrades cleanly when `stop_times.csv` is absent (the file is 26 MB and optional) — it drops
  to `distance` and says so.
- A trained model will eventually beat this. That is fine: the log this design produces is the training
  set and the benchmark that would make such a model justifiable.
- If the ETA work slips, `iett_next_arrivals` still ships with "how many stops away + planned departure",
  and the minute estimate becomes a stretch (PLAN.md §11).

---

## 5. The LLM is swappable through environment variables

**Date:** 2026-09-08 · **Status:** Accepted

### Context

The model is the one component this project cannot guarantee access to. Azure for Students subscriptions
frequently have **zero Azure OpenAI quota** and a region refusal (documented in Microsoft Q&A, July 2026);
a Foundry serverless "sold by Azure" deployment was reported working by a student in September 2026;
Foundry Local runs on the development machine today. **GitHub Models was retired on 30 July 2026**, so the usual
free fallback does not exist. Discovering the answer costs a Day-0 gate, and it may change mid-sprint if
a quota request is approved.

### Decision

Neither the agent nor the eval judge names a provider. Both read `LLM_BASE_URL`, `LLM_MODEL` and the
corresponding key from the environment and speak the OpenAI-compatible protocol, so Azure OpenAI, a
Foundry serverless endpoint and Foundry Local are one variable apart. The selection order is the decision
tree in PLAN.md §9: try Azure OpenAI, file the student quota request immediately if refused, then Foundry
serverless, then Foundry Local. Where Foundry Local's tool-calling proves unreliable, the fallback is a
JSON-output contract plus a dispatcher in agent middleware rather than a different architecture.

### Consequences

- A quota approval mid-sprint is a configuration change, not a refactor.
- The constraint becomes a feature: the same agent demonstrated on Azure *and* on-device is a real
  edge-versus-cloud statement about public-sector data.
- The eval judge may not be the same model as the agent. Whichever was used is recorded in
  `eval/results/`, because a judge swap changes the numbers.
- Small local models call tools less reliably; the JSON-and-dispatcher fallback is extra code that exists
  only for that case.

---

## 6. Delta Lake for silver and gold rather than plain Parquet

**Date:** 2026-09-08 · **Status:** Accepted

### Context

The collector writes on timers — fleet positions every 2 minutes, İSPARK every 10, the rest hourly. That
produces a stream of small files, and timers fail and get retried, so the same window can be written
twice. Downstream, the same tables should be readable by ADX and, on the roadmap, mirrored by a Fabric
OneLake shortcut.

### Decision

Bronze stays raw `JSON.gz`, exactly the bytes İBB returned, append-only, so any parsing bug can be
replayed from source. Silver and gold are **Delta Lake** tables written with `deltalake`.

> **2026-09-23, as implemented — this entry describes the plan, not the code.** Bronze holds the
> *parsed* rows as gzipped NDJSON, with the number plate already dropped by the parser (decision 7),
> not the verbatim upstream body: `src/nabiz/collector/lake.py` writes those rows, and the Azure path
> writes them to ADLS through `azure-storage-blob`. No silver or gold writer exists; the containers are
> created by the template and stay empty (`docs/deploy.md` §8), and the `job` extra carries no
> `deltalake`. Changing bronze to hold the upstream body would bring the plate back into the lake
> (`docs/deploy.md` §1 says what must change first). A superseding entry is due when silver and gold
> are either built or dropped.

### Consequences

- ACID commits and merge/upsert make a retried timer idempotent instead of a duplicate-row problem.
- Time travel answers "what did we know at 08:00?" when auditing an ETA that was wrong — an audit trail
  that plain Parquet cannot provide.
- Compaction is a supported operation rather than a bespoke rewrite job, which matters for a 2-minute
  write cadence.
- OneLake shortcuts and ADX external tables both read Delta, so the Fabric mirror on the roadmap needs no
  data migration.
- Costs one dependency (`deltalake` plus `pyarrow`) and a little write overhead. Plain Parquet remains the
  fallback if the Functions Flex package size becomes a problem.

---

## 7. Bus number plates are dropped at the parsing boundary

**Date:** 2026-09-08 · **Status:** Accepted

### Context

`GetFiloAracKonum_json` returns 6 911 vehicles, and each record contains `Plaka` — the number plate. A
plate joined to a timestamped coordinate is location data about an identifiable driver over the course of
a shift. Nothing in this project needs it: the door number (`KapiNo`) identifies a vehicle for every
purpose here, including matching a bus to its later arrival in the ETA log. The Azure Data Explorer free
cluster terms also prohibit storing personal data.

### Decision

The plate is discarded at the **earliest possible point**, inside `BusPosition.from_fleet_raw`
(`src/ibb_mcp/models.py`). No layer above the parser ever receives it: not the cache, not the lake, not
ADX, not a tool result, not a log line. Door number is the vehicle identity throughout.

### Consequences

- The guarantee is enforced in one function rather than repeated as a rule in the collector, the lake
  writer and the API layer — a reviewer has exactly one place to check, and it is named in
  [NOTICE.md](NOTICE.md).
- We cannot follow a vehicle across a plate change or join to any external plate-keyed dataset. We have no
  use for either.
- Bronze holds the raw upstream response, so the retention policy on the bronze container is the one
  remaining place where this needs attention; that is called out in the collector's ADR when it lands.
  *(2026-09-23: superseded by what was built. Bronze stores the parsed, plate-free rows as gzipped NDJSON
  (see the note under decision 6), so the plate never reaches the lake and the bronze retention rule is a
  cost bound, not a privacy control — `docs/deploy.md` §1.)*

---

## 8. `src/` layout with two packages instead of the `packages/` layout in PLAN.md

**Date:** 2026-09-08 · **Status:** Accepted — supersedes the repository sketch in PLAN.md §12

### Context

PLAN.md §12 sketched `packages/ibb_mcp/` with its own `pyproject.toml` alongside `src/collector`,
`src/agent` and `src/web`. That is a workspace: two dependency trees, two lockfiles, two test
configurations and two build steps. In a seven-day sprint that overhead is paid every day, while the
benefit — independent versioning — is needed only once, at publication time. But the underlying goal is
real: `ibb-mcp` should be installable by someone who wants İBB data in their own agent and has no interest
in this project's Azure deployment.

### Decision

One `pyproject.toml` at the repository root, `src/` layout, two packages:

- **`src/ibb_mcp/`** — the MCP server. Depends only on `httpx`, `pydantic` and `mcp`. **Imports nothing
  from `nabiz`** — a rule that holds today only because nothing is reviewing it: there is no test
  asserting it, and adding one is a prerequisite of the extraction described below.
- **`src/nabiz/`** — the Azure-facing application: `collector/`, `agent/`, `web/`. The directories exist;
  the code arrives on Days 1 and 4–5.

Azure, Delta, agent and web dependencies live in optional groups (`collector`, `web`, `agent`, `dev`), so
installing the server does not drag in `azure-functions`, `deltalake` or `fastapi`.

### Consequences

- `uv pip install -e ".[dev]"` sets up everything; one `pytest` run, one CI job, one ruff configuration.
- The dependency rule keeps the extraction mechanical: publishing `ibb-mcp` separately later means adding
  a package-level manifest and moving a directory, with no import untangling. Unenforced, it is a habit
  rather than a guarantee — a one-line import-graph test is owed before `src/nabiz/` has any code in it.
- Someone installing from PyPI gets a light dependency set: three runtime packages.
- The trade-off is that until that publication happens, the server and the application share a version
  number.

---

## 9. Pivot from "Nefes" (air-quality early warning) to "Nabız" (city agent)

**Date:** 2026-09-08 · **Status:** Accepted · Archived plan: [`docs/archive/PLAN-nefes-v2.md`](docs/archive/PLAN-nefes-v2.md)

### Context

The previous plan, Nefes v2, was a well-specified air-quality early-warning platform: hourly PM10
forecasting, threshold exceedance with lead time and false-alarm rate, an analyst agent drafting
warnings. Its problem was not technical. Its user was **a hypothetical İBB operator watching a dashboard**
— a person who does not exist, who was never going to open it, and whose "decision" was invented to
justify the build. That makes a dashboard, not a product, and it shows: nothing in the design would have
changed if the forecast had been ignored.

İstanbul already has İBB apps for parking, buses, air and metro. What it does not have is a single
conversational surface across them, an open integration layer any developer can plug in, or an answer to
"what is it *usually* like at this hour". Those three gaps have a real user — anyone driving, catching a
bus, taking the metro or going for a run in İstanbul — and a real second user, the developer who mounts
the MCP server in their own agent.

### Decision

Pivot to **Nabız**: six İBB sources behind one MCP server plus a city agent, with the four journeys in
PLAN.md §1 as the spine of both the product and the eval. The air-quality work is not discarded — it
becomes journey J4 and the `air_quality_now` / `air_quality_forecast` tools. The old plan is archived
verbatim rather than deleted.

### Consequences

- Everything already verified about the İBB endpoints, and the air-quality history reaching back to 2023,
  carries over unchanged.
- Scope grew from one source to six. That is absorbed by the shared client, cache and tool envelope
  (decision 3) rather than by six bespoke integrations.
- The air-quality forecast is timeboxed to three hours and ships as a seasonal-naive baseline unless a
  trained model beats it; both results are reported, never just the better one.
- The headline evidence changes from forecast accuracy to **task success rate and measured ETA error** —
  metrics about whether a person got a usable answer, which is what the pivot was for.
- The 100-requests-per-hour İETT limit, previously irrelevant, became the central engineering constraint
  (decision 3).

---

## 10. The collector runs as scheduled Container Apps Jobs, not on the laptop or Functions timers

**Date:** 2026-09-23 · **Status:** Accepted by the owner; written and tested offline, **not yet deployed**

### Context

The history İBB does not publish only exists while something collects it, and nothing has collected it
reliably:

- **The laptop collector keeps stopping.** Commit 0951bcc records two deaths (machine sleep, parent shell
  gone) and adds `scripts/supervise_collector.sh`. It kept stopping under the supervisor: the laptop's
  own lake has `iett_line_snapshot` partitions for 8, 13, 14 and 22 September only — **4 of the 15 days
  from 8 to 22 September** (`data/lake`, untracked, listed on 23 Sep). Those days are unrecoverable.
- **The Azure Function would not have collected the headline series.** `function_app.py` has five timers —
  İSPARK, fleet, metro, traffic, air quality. Watched lines and the ETA prediction log ran only in
  `scripts/collect_forever.py`, and `kusto.TABLES` had no table for either, so `KustoSink` dropped them.
  Those two series are exactly the observed arrivals and predictions the measured ETA error (README
  §Results) is computed from. The Function was also never deployable as packaged (no `host.json`, no
  `requirements.txt`, imports outside the zipped directory — docs/deploy.md §5).
- **The İETT budget lives in process.** `PoliteClient` allows 80 İETT requests per sliding hour against
  the 100 İETT documents (#3). A run-once process that makes three requests and exits never fills that
  counter; every execution would start with a full budget.

### Decision

Five **scheduled Container Apps Jobs** (`Microsoft.App/jobs@2024-03-01`, `infra/modules/collectorjobs.bicep`)
run `python -m nabiz.collector.job` from the MCP server's image (#11), in the MCP server's
Consumption-only environment. Cron is five-field UTC; the laptop cadences are kept and grouped where they
coincide:

| Job | Cron (UTC) | Sources → tables | İETT requests / run | Peak runs / hour | `replicaTimeout` |
|---|---|---|---|---|---|
| `lines` | `*/3 * * * *` | `lines` → `iett_line_snapshot`, `eta_predictions` | 3 | 20 | 170 s |
| `city` | `1-59/10 * * * *` | `ispark` → `ispark_snapshot`; `fleet` → `iett_fleet_snapshot` | 1 | 6 | 300 s |
| `metro` | `5 * * * *` | `metro` → `metro_status` | 0 | 1 | 300 s |
| `traffic` | `10 */6 * * *` | `traffic` → `traffic_index_hourly` | 0 | 1 | 300 s |
| `airquality` | `16 */12 * * *` | `air_quality` → `aq_hourly` | 0 | 1 | 900 s |

(`.venv/bin/python -m nabiz.collector.job --plan` prints this from the code.) What makes it safe:

- **The İETT budget is enforced by the schedule.** Peak runs in any rolling hour × İETT requests per run,
  summed: 20 × 3 + 6 × 1 = **66**, under the client's 80. `tests/test_collector_job.py` computes it from
  `SCHEDULES`, pins it at 66, and checks that `infra/main.bicep` declares the identical schedule. At run
  time each execution replaces the client's budget with one holding exactly its planned requests, so an
  unplanned extra call is refused and logged instead of spent (tested with a counting mock transport).
- **One attempt per İETT request, no replica retries** (`replicaRetryLimit: 0`). A retry is an unplanned
  request; with the client's default three attempts a failing gateway would triple the spend. The next
  scheduled execution is the retry. Sources that do not touch İETT keep the default backoff.
- **Fleet drops from every 2 minutes to every 10.** At the Function's cadence (30 requests/hour) plus
  lines (60) the total would be 90, over the 80 limit. Nothing in the repository reads
  `iett_fleet_snapshot` today; it is kept, at the cadence the budget allows, for the line-speed profile.
- **The ETA log is the laptop's, unchanged.** `nabiz.collector.eta_log` is a port of
  `build_eta_predictions`: same watched lines, same targets, same engine inputs. A test loads the running
  laptop script read-only and requires identical output on the same input, so the error measured after
  the move is comparable with the one measured before it.
- **Traffic is read without the laptop's gap.** The laptop keeps 3 hourly buckets every 6 hours, so three
  of every six hours were never recorded (its 20:54 UTC tick on 13 Sep holds 18–20 h, the next one
  00–02 h). The job keeps 7 per 6-hour run: one hour of overlap.
- **Deadline, exit code, logs.** `--deadline-s` (`replicaTimeout` − 30 s) stops reading in time to write
  what was read. A source is `ok` (rows written), `empty` (reads succeeded, İBB had nothing — 19 of the
  laptop's line ticks between 01:50 and 04:06 on 14 Sep were exactly that) or `failed`; the process exits
  1 only if every source failed, so the platform's execution history means something. Each execution
  ends with one JSON line tagged `collector-job` for Log Analytics.
- **One collector identity** (`id-collector-<token>`, now `modules/collectoridentity.bicep`) writes the
  lake and pulls the image. It is the identity the Function used, so the hand-written ADX grant survives
  a change of host.

### Alternatives considered

- **Keep the laptop, better supervised.** Free, and already written. Rejected on the evidence above: four
  days in fifteen. A laptop that closes its lid is not infrastructure.
- **Add `lines` and ETA timers to the Function.** Keeps one collector codebase, but inherits the
  unresolved packaging problem and the unverified hierarchical-namespace risk on the Functions host
  storage (docs/deploy.md §1), and a second deployment artifact (a zip) next to the image. The Function
  stays in the template, off by default (`deployCollectorFunction`), as the fallback for a region that
  refuses Container Apps. Its cost was not re-priced for this decision.
- **An always-on Container App running `collect_forever.py` unchanged.** Keeps the in-process budget and
  needs no new code. But one 0.25 vCPU / 0.5 GiB replica for 30 days is 648,000 vCPU-s and 1,296,000
  GiB-s — 3.6 × the monthly vCPU grant — so $5.62/month if all of it bills at the idle rate and $19.66 at
  the active rate (prices below), and it leaves no free grant for the MCP server. It also keeps the
  failure mode that motivated this: one long-lived process that can stop quietly.
- **One job every 3 minutes that picks sources by the clock.** Fewer executions: the 5,220 extra
  executions a month of the other four jobs cost about 104,000 execution-seconds of assumed start-up,
  roughly 16 % of the estimate below. Rejected because the cadence would be hidden in code instead of
  in cron, and the 3-minute air-quality read would overrun the next tick.

### Cost

Inputs, each with its source:

- **Price** (West Europe, Consumption, active): $0.000034 per vCPU-second, $0.000004 per GiB-second — Azure
  Retail Prices API (`prices.azure.com`, `serviceName eq 'Azure Container Apps'`), queried 2026-09-23.
- **Free grant**: the first 180,000 vCPU-seconds and 360,000 GiB-seconds per subscription per calendar
  month; jobs are charged the active rate and never request charges
  (learn.microsoft.com/azure/container-apps/billing). The MCP server shares the same grant.
- **Size**: 0.25 vCPU / 0.5 GiB per execution, the smallest Consumption pair. The heaviest execution run
  locally (`lines` with the GTFS index loaded, offline fixtures) peaked at 105,906,176 bytes resident
  (`/usr/bin/time -l`), about a fifth of 0.5 GiB. Without the Azure SDKs, which are not installed here.
- **Run time**: the laptop's median tick for the same work (lines 12.1 s, İSPARK 0.3 s, metro 0.1 s,
  traffic 5.8 s, air quality 174.1 s; `logs/collector.log`, 13–23 Sep) **plus an assumed 20 s** of
  container start per execution — not measured, because nothing has been deployed. `city` adds the 6 s
  gate and an assumed 10 s fleet read: the laptop never collected fleet.

| Job | Executions / 30 days | Seconds each | Execution-seconds |
|---|---|---|---|
| `lines` | 14,400 | 32.1 | 462,240 |
| `city` | 4,320 | 36.3 | 156,816 |
| `metro` | 720 | 20.1 | 14,472 |
| `traffic` | 120 | 25.8 | 3,096 |
| `airquality` | 60 | 194.1 | 11,646 |
| **Total** | **19,620** | | **648,270** |

That is 162,068 vCPU-s (90 % of the grant) and 324,135 GiB-s (90 %): **$0.00 a month** on this estimate,
with little room left for the MCP server. The assumption that moves it most is the start-up time:

| Scenario | vCPU-s / GiB-s (% of grant) | Beyond the grant |
|---|---|---|
| Laptop median + 20 s start (above) | 162,068 / 324,135 (90 %) | $0.00 / month |
| Laptop p95 + 20 s start | 186,753 / 373,506 (104 %) | $0.28 / month |
| Laptop median + 40 s start | 260,168 / 520,335 (145 %) | $3.37 / month |
| Ceiling: every execution runs to `replicaTimeout` | 1,012,500 / 2,025,000 | $34.97 / month |

The ceiling is what a hung gateway on every tick — or a job running a web-server image, see #12 — would
cost, and it is the reason for the budget alert in docs/deploy.md. Each hour the 0.5 vCPU / 1 GiB MCP
server is active beyond the grant adds $0.0756. Replace every estimate here with measured execution times
after the first day (`az containerapp job execution list`, docs/deploy.md §4.4).

### Consequences

- The laptop can be switched off (`make collect-stop`) once the jobs have run — docs/deploy.md §4.3 gives
  the order, because a laptop and the jobs together spend two İETT budgets against one limit.
- The İETT budget is now a property of the schedule and is tested. Changing a cron, a source's request
  count or the watched lines changes a pinned number, deliberately.
- **Still open:** the MCP server keeps its own in-process 80/hour. If it is used heavily for İETT tools in
  the same hour, server and jobs together can exceed İETT's 100. The laptop and a local server had the
  same exposure. Closing it needs one shared budget (a counter in the lake, say); not in this change.
- Two of the six `city` executions an hour start in the same minute as a `lines` execution: two request
  streams, each 6 s apart, not the ~15-call burst that trips the gateway. No other jobs share a start
  minute (tested).
- Fleet positions have 10-minute resolution, not 2.
- History now lands in Blob Storage (`bronze/`, same layout). `scripts/eta_report.py`,
  `calibrate_eta.py` and `reliability_report.py` read `data/lake`, so they need a sync first
  (docs/deploy.md §4.5) — and the 30-day bronze lifecycle rule deletes cloud history that is neither
  synced nor in ADX.
- `azure.yaml` no longer lists the Function as a service, and `NABIZ_COLLECTOR_CLIENT_ID` now comes from
  the shared identity.
- **Not verified:** no Bicep compile on this machine (CI compiles it), no deployment, no image build, no
  measured run time in Azure.

---

## 11. One container image for the MCP server and the collector, harvested from the ops branch

**Date:** 2026-09-23 · **Status:** Accepted; the image has **not yet been built**

### Context

`azure.yaml` pointed the `mcp` service at a `Dockerfile` that `main` did not have (docs/deploy.md §5.2 said
so). The `feat/ops-hardening` work in the `nabiz-ops` worktree (13 Sep, uncommitted) had one, with a
`.dockerignore`. Its handoff also listed three more gaps as "addressed on this branch" — no `kql/`, two
sources without an ADX table, a deployed collector without lines or ETA — but that worktree's
`git status` and `git diff` on 23 Sep show no `kql/` files and no change under `src/nabiz/collector/`.
They are addressed here instead: #10, `kusto.TABLES`, `kql/schema.kql`.

### Decision

Harvest the branch's `Dockerfile` and `.dockerignore`, and make the image serve both uses:

- **One image, two commands.** The CMD starts `ibb-mcp`; each collector job overrides `command`/`args`
  with `python -m nabiz.collector.job`. azd builds one image per service, and five jobs as five services
  would be five remote builds of the same tree on every deploy.
- The build installs `.[job]` — a new optional extra with the Azure identity, Blob Storage and ADX client
  libraries the collector writes with — and **imports them during the build**, because pip only warns
  about an unknown extra and the failure would otherwise surface as every collector write failing in
  Azure. The extra is declared in `pyproject.toml`, and `tests/test_server_security.py` checks that the
  extras the `Dockerfile` installs exist.
- Two stages, non-root user, no pinned platform (azd's remote build runs on linux/amd64), GTFS baked in
  when present with a build-time line saying whether it is.
- `.dockerignore` is an allow-list. Without it a remote build uploads roughly 250 MB: `.venv` is 72,288
  KiB, `data/reference/gtfs` 179,928 KiB and `data/lake` 4,200 KiB here (`du -sk`, 23 Sep), while the
  image needs the source tree and about 2.4 MiB of GTFS.
- Corrected while harvesting: the branch's comments cited `tests/test_packaging.py`, which exists in
  neither tree; the checks the collector relies on are now in `tests/test_collector_job.py`. The
  `HEALTHCHECK` targets `/healthz`, which the server hardening from the same branch serves (#15).

### Alternatives considered

- **A separate collector image**: smaller server image, but a second azd service or a hand-run build,
  and two images to keep in step with one source tree.
- **Pinning the SDKs in the Dockerfile** instead of an extra: no `pyproject.toml` change, but the
  versions would live in two places.

### Consequences

- The MCP server's image carries client libraries it never imports; the size cost is unmeasured (no
  Docker daemon on the development machine).
- The first build anyone runs is the owner's `azd deploy mcp`. Were the `job` extra ever dropped from
  `pyproject.toml`, that build would fail at the import check — by design.
- An image built on a machine without `data/reference/gtfs` serves every tool except the two GTFS-backed
  ones, and its `lines` executions log an ERROR on every tick because the ETA log cannot run.
- The branch's `tests/test_infra.py` (offline structural checks of `infra/`) is now part of the suite:
  20 passed against these templates.

---

## 12. Provisioning takes the deployed image as an input, and never deploys a job with a placeholder

**Date:** 2026-09-23 · **Status:** Accepted

### Context

`containerapps.bicep` fell back to the public quickstart image whenever `mcpContainerImage` was empty,
which is always under azd. So every `azd provision` — which docs/deploy.md asks for after setting the ADX
URI or changing a knob — put the live MCP server back on the placeholder until the next `azd deploy`.
For a scheduled job a placeholder is worse than broken: a web server never exits, so every execution runs
to `replicaTimeout` and bills for it — the $34.97/month ceiling in #10.

### Decision

- `infra/main.parameters.json` passes `SERVICE_MCP_IMAGE_NAME` — which azd sets when it deploys the `mcp`
  service — into `mcpDeployedImage`. The MCP app runs the pinned image if there is one, else the deployed
  one, else the placeholder (first provision only).
- The collector jobs run the pinned or the deployed image and are **not deployed at all** when there is
  neither (`deployJobs` in `main.bicep`). A new environment therefore takes `azd up`, then `azd provision`.
- The collector identity is created unconditionally, apart from any host, so its client id — the one the
  ADX grant names — is stable however many times either host is provisioned.

### Alternatives considered

- **The azd "upsert" pattern** (`SERVICE_<NAME>_RESOURCE_EXISTS` and the AVM `container-app-upsert`
  module): solves the revert for the container app, but not the jobs, and replaces a hand-written module.
- **A `postdeploy` hook running `az containerapp job update --image`**: updates the jobs immediately, but
  mutates infrastructure outside Bicep and needs `az` inside an azd hook. The hook prints a reminder
  instead.

### Consequences

- After a code change the jobs keep the previous image until `azd provision`; the `mcp` postdeploy hook
  says so. A provision no longer breaks the running server.
- **Not verified:** that azd persists `SERVICE_MCP_IMAGE_NAME` in `.azure/<env>/.env` after a deploy. The
  azd documentation says the variable is set during deploy; docs/deploy.md §4.2 checks it and gives the
  one-line manual fallback.

---

## 13. Alerts are evaluated statelessly; the client holds the subscription and the cooldown

**Date:** 2026-09-13 (engine), 2026-09-23 (web route and MCP tool) · **Status:** Accepted

### Context

An alert about "my home" or "my car park" needs the user's places, and a place is a coordinate. A
server that keeps coordinates per user holds personal data under KVKK (Law No. 6698): it needs a legal
basis, a retention policy, a deletion path and a database, none of which a one-person student project
can operate well. The ADX free cluster's terms also forbid personal data (#7). There are no accounts.

### Decision

- `nabiz.alerts.engine.check_alerts` evaluates a subscription that arrives **with each request** and is
  forgotten when the request ends. No database, session, cookie or user identifier exists.
- The **cooldown is the client's**. Each alert carries a `dedupe_key` and `cooldown_seconds`; the client
  remembers what it has shown and sends the keys it is sitting on as `muted_keys`.
- Two doors, one engine: `POST /api/alerts/check` takes the subscription in the request **body**, never a
  query string, because a query string lands in access logs; the MCP tool `check_alerts` advertises a
  typed schema (`src/nabiz/alerts/schema.py`) that describes the payload and bounds its lengths, while
  the engine stays the single validator. Its refusals name a place key, never a coordinate.
- The GET routes that take a place (`/api/parking`, `/api/route`) accept gazetteer names only.
- The web agent does not offer `check_alerts` (`NOT_OFFERED`, now in `src/nabiz/agent/schemas.py`): it holds
  no subscription to send.

### Alternatives considered

- **Server-side subscriptions with push notifications**: the feature people expect, and a database of
  where people live and work.
- **Storing hashed coordinates**: a hash of a coordinate on a city grid is reversed by trying the grid;
  still personal data.

### Consequences

- No push notifications: the page checks when it is open. Clearing browser storage forgets the
  subscription, and the page's reset control does exactly that on purpose.
- Through an MCP client the coordinates are part of that client's conversation with its own model
  provider before they reach us; `docs/privacy.md` §4 says so.
- The hosting platform can still log addresses and paths; disabling or minimising ingress access logs
  is a deployment gate before real users (`docs/privacy.md` §4, item 2).
- The page can evaluate and reset a subscription but has no editor to create one yet
  (`docs/privacy.md` §8).

---

## 14. Compare travel modes over a distance-justified rail graph; do not plan routes

**Date:** 2026-09-23 · **Status:** Accepted — narrows PLAN.md §17 for the comparison slice · Design note:
[docs/route-advisor.md](docs/route-advisor.md)

### Context

Journey E1 asks "arabayla mı, metroyla mı?" while PLAN.md §17 rules out route planning. Two advisors
existed: `routing.py` on `main` (`plan_journey`) and `advisor.py` in the uncommitted `feat/route-advisor`
worktree. Main's rail estimate took the straight line between the nearest stations at each end with at
most one guessed transfer; over the 16,370 same-side station pairs more than 2.5 km apart that have a rail
path, it gave too few transfers for 9,145. Matching transfers by station name instead invents a 64-minute
Kadıköy → Taksim trip through Bahariye, a name shared by a T3 stop and an M9 station 20.7 km apart
(docs/route-advisor.md §4, measured 2026-09-23 on the recorded station list).

### Decision

- One advisor, `routing.compare_options`, behind the existing `plan_journey` tool. No new MCP tool.
- Rail rides `metro_graph.MetroGraph`: a transfer exists only where distance justifies it (≤ 250 m within
  a station, ≤ 800 m on foot for a shared name, ≤ 350 m otherwise), and the rejected same-name pairs are
  published. The Bosphorus is crossed only through the Marmaray tube, added as rows the caller vouches for
  on four stations the feed already has (Yenikapı, Sirkeci, Üsküdar, Ayrılık Çeşmesi).
- Bus: `lines.StopRouteIndex` is the one direction-aware scan; one line is costed, other direct lines are
  named with stop counts and no minutes.
- A weekday × hour traffic norm from İBB's own 28-day history is reported beside the drive estimate,
  never folded into it.
- An unread source is reported as unknown, never as good news: unread metro notices are not "no
  disruption", an unread İSPARK list is not "no free space".

### Consequences

- Rail minutes are estimates with one published check (M7: 38.9 min modelled against Metro İstanbul's 36)
  and a flat 6-minute headway. The drive estimate has no ground truth, and `fastest_mode` ranks estimates,
  each labelled `kind: estimate`.
- One more upstream read: the `/28/H` traffic history, at most once per six hours per process.
- The `feat/route-advisor` worktree holds nothing that is not on `main` (docs/route-advisor.md §9).
- A real router would supersede this decision, not extend it.

---

## 15. Harden the public MCP endpoint: stateless transport, per-tool token buckets, optional key, closed CORS

**Date:** 2026-09-23 · **Status:** Accepted — not yet deployed

### Context

Over HTTP nothing stood between a script with a loop and the İETT allowance every user of this project
shares (THREAT_MODEL MCP-5). The ops-hardening worktree found the gap — no authentication, no per-client
limit, no CORS policy — and left its fix unwired. Two more problems were measured while porting it on
23 Sep: in the SDK's default stateful mode every `initialize` holds a session, and `initialize` is never
charged, so a loop of them fills the SDK's session cap for everyone; and uvicorn's
`--forwarded-allow-ips '*'` trusts the leftmost `X-Forwarded-For` entry, which a caller writes. A
4,000,000-character place name also took 14.9 s of the event loop, against about 1 ms for 120 characters.

### Decision

- `ToolBudget`, an MCP middleware, charges each `tools/call` to its caller's token bucket at the tool's
  price, set by how far upstream it can reach on a cold cache: 1 + gateway GETs + 4 per İETT SOAP call
  (`TOOL_COSTS` in `src/ibb_mcp/server.py`). A refused call is a readable `rate_limited` result with
  `retry_after_seconds`.
- An API key is optional (`NABIZ_API_KEYS`), compared in constant time, and counts as a caller's identity
  only once accepted. CORS is closed unless origins are configured.
- The transport runs **stateless**; no tool needs a session.
- The request body is capped at 64 KiB, and every free-text parameter has a length limit in its
  advertised schema (120 characters for a name, 16 for a code).
- The caller's address is the entry the configured number of trusted proxies appended
  (`NABIZ_MCP_TRUSTED_PROXY_HOPS`, set to 1 behind the Container Apps ingress); IPv6 is grouped by /64;
  the limiter and the log hold only a salted per-process pseudonym.
- `/healthz` answers from process state and local files alone, never from İBB.

### Consequences

- Budgets live in process, which keeps the one-replica ceiling of #3; a cached answer still costs tokens,
  because the price is the worst case.
- A stateless server cannot send requests to the client (sampling, elicitation); nothing here uses them.
- Whether the key is required before a public launch is the owner's decision; the default is open, with
  per-caller budgets.
- The trusted-hop count must be confirmed against the real ingress on the first deploy.

---

## 16. Every span goes through one allow-list; no auto-instrumentation

**Date:** 2026-09-23 · **Status:** Accepted — not yet deployed

### Context

Traces go to Application Insights, a server-side store, so a span attribute falls under the same privacy
rule as the lake. The ops-hardening worktree wrote a telemetry shim and never called it. With a
connection string set, the Azure Monitor distribution would also have instrumented FastAPI, whose spans
record the full URL (`/api/route?from=…&to=…`), and forwarded log records.

### Decision

- `nabiz.agent.telemetry` (since #19 `ibb_mcp.telemetry`, the old name an alias) is the only way to make a
  span. It drops every attribute not on
  `ALLOWED_ATTRIBUTES`, records an exception's type but never its message (tool errors quote the user's
  input back), and degrades to no-ops when OpenTelemetry is absent.
- Upstream spans keep host and path, never the query string; tool spans carry the tool name and outcome,
  never arguments; agent spans carry the mode, the tools and the faithfulness verdict, never the question
  or the answer.
- The distribution's auto-instrumentation and its log and metric export are switched off; the managed
  identity is used when Entra authentication is asked for.
- A separate `telemetry` extra, so the MCP image can trace without a model SDK.

### Consequences

- Traces cannot answer "what did people ask", by design.
- The distribution's options were verified against a fake in the tests, not against the real package,
  which is not installed on the development machine; the first deploy must confirm that only `nabiz.*`
  and MCP spans arrive.
- The container image does not install the `telemetry` extra yet, so nothing is exported until it does.

---

## 17. Tests and CI read only committed, scrubbed data

**Date:** 2026-09-23 · **Status:** Accepted

### Context

CI failed on all of its first 13 runs on `main`. Ten failed on the same three `tests/test_web.py` tests,
which read the GTFS export in `data/reference/gtfs/`: gitignored, and present only on the laptop that
downloaded it. The other three failed at the lint gate, hidden behind a main that was already red. Separately,
the recorded fleet fixtures, which are published with the code, held 60 real bus number plates
(`tests/fixtures/iett_fleet.json`) and 21 in the SOAP capture, although #7 promises plates never leave the
parser.

### Decision

- Tests read GTFS from `tests/fixtures/gtfs_mini`, a 38 KB cut of İBB's export copied byte for byte, so the
  defects the loaders repair (BOM, `;`, CRLF, thousands-separated coordinates, mojibake) are still there.
  `extract.py` rebuilds it and checks the rebuilt sequences against the full feed. The shared test
  settings read a per-session copy, because the sequence cache is written beside the tables.
- Every plate in the recorded fixtures is synthetic (`00 XX 001` … `00 XX 060`; province 00 does not exist),
  and `scripts/capture_fixtures.py` swaps plates before it writes anything.
- `scripts/guardrails.py` encodes the incidents already had (plates, collapsed schemas, raw İBB calls,
  secrets, personal data, AI credit, unsourced README numbers) and runs in CI; `scripts/check_authorship.py`
  checks the identity and message of every pushed or proposed commit. Neither needs the network.
- `make ci-local` reproduces CI on a copy of exactly what a push would publish, which is the check that
  would have caught the gitignored dependency.

### Consequences

- A test that needs a stop or a trip outside the cut needs the cut extended with `extract.py`, not a read
  of the local export.
- The real plates remain in the public history from the bootstrap commit; only a history rewrite removes
  them (docs/THREAT_MODEL.md §5.3).
- The offline eval harness still reads `data/reference/gtfs` (`eval/run_eval.py` builds its settings
  directly). Run on the clean copy `make ci-local` builds (23 Sep), it scored 26/30: the four J2 scenarios
  that search stops or estimate arrivals failed on the missing export. On a machine with the export: 30/30.

---

## 18. Serve the arrival estimator with the better held-out score: the untuned rate

**Date:** 2026-09-23 · **Status:** Accepted — supersedes the tools' use of the calibrated profile (commit
`c306157`); owner-approved principle: serve the estimator with the best held-out score

### Context

`c306157` fitted seconds-per-stop rates per line and time of day (`data/reference/eta_profile.json`,
`scripts/calibrate_eta.py`) and `iett_next_arrivals` and the bus option of `plan_journey` started using
them. Its figures (16.83 -> 11.16 min MAE) are **in-sample**: the error of the fitted rates on the 500
predictions they were fitted on, all at two 500T stops (`eval/results/eta.md`, "What 12.37 and 11.2 are").

The first test on data the fit never saw is the held-out replay in `eval/results/eta.md`
(`scripts/eta_holdout.py`, `make eta-holdout`): every stop-sequence prediction made after the profile was
frozen, whose 90-minute match window the collector fully covered, re-timed with the rate the tool would
have chosen. On those **523 predictions, at stops the calibration never saw, the calibrated profile scored
35.82 min MAE (bias +35.6) against 10.18 min (bias +9.1) for the untuned 120 s/stop** the predictions were
actually logged with. It was worse in every cell: 500T evening 64.62 vs 7.85 (n = 175), 500T night 21.70 vs
12.14 (n = 310), 15F on the pooled rate 20.54 vs 5.61 (n = 32), 34 on the pooled rate 6.54 vs 1.73 (n = 6).
Seconds per stop is a property of a stretch of road, not of a line: at the old targets a bus took a median
283–379 s per remaining stop, at the new 500T targets 63–93 s.

Limits, stated in the same file: a replay, not a live measurement; 485 of the 523 rows are 500T from one
evening and one night (13–14 Sep); the lake behind it is gitignored, so the figures cannot be re-derived
from a clone.

### Decision

- `iett_next_arrivals` and the bus leg of `plan_journey` serve the **untuned default** (120 s/stop,
  `ibb_mcp.eta.DEFAULT_PARAMS`), chosen in one place: `ibb_mcp.eta_profile.served_rate`. In that mode
  the profile file is not read at all.
- The calibrated profile is used only when the operator sets **`NABIZ_ETA_PROFILE_MODE=calibrated`**
  (`Settings.eta_profile_mode`), for research. Any other value serves the default and says why.
- Every arrival answer says which rate it used and why: `diagnostics.rate_mode` (`default` /
  `calibrated`), `rate_source` (the rung of the fallback chain), `rate_reason` (the numbers above and this
  file) and `seconds_per_stop`. The disclaimer says the measured rates are withheld because they did worse
  on unmeasured stops, not that nothing was measured; the journey's `bus_seconds_per_stop` assumption says
  the same (`ibb_mcp.routing.DEFAULT_RATE_DETAIL`).
- The profile, `scripts/calibrate_eta.py` and `scripts/eta_holdout.py` stay: calibration is how the next
  fit will be made, and the held-out replay is how it will be judged before it is served again.

### Consequences

- 500T riders get 120 s/stop instead of the fitted cells (evening 445, midday 250, night 160 s/stop, and the
  line's 235 in the morning, which has no cell), and every other line gets it instead of the pooled
  235 s/stop that was fitted on 500T alone (`data/reference/eta_profile.json`).
- The measured 12.94 min MAE in `eval/results/eta.md` (1,351 resolved predictions, all logged at 120 s/stop
  by the collector) now describes the estimator the tools serve, not a predecessor of it.
- A future calibration is served again only when its held-out score beats the default's on the same kind
  of replay; the switch is the one setting above, and this entry is then superseded, not edited.

---

## 19. The server package imports nothing from the apps, and code size is ratcheted

**Date:** 2026-09-23 · **Status:** Accepted

### Context

#8 promised that `ibb_mcp` imports nothing from `nabiz`, and noted that the rule held "only because nothing
is reviewing it". By 2026-09-23 it no longer held: `ibb_mcp.server` and `ibb_mcp.tools` imported the alert
engine from `nabiz.alerts`, and `ibb_mcp.http` and `ibb_mcp.server` the tracing shim from
`nabiz.agent.telemetry`, so `import ibb_mcp.server` loaded seven `nabiz` modules (measured with
`sys.modules` at `d59b5a8`). Two source modules imported other sources for a text helper, and three public
functions named `normalize_tr` folded Turkish text three ways. Module and function sizes had grown by the
hour during the sprint.

### Decision

- The alert engine, its rules and the MCP subscription schema live in `ibb_mcp.alerts`; the tracing shim
  in `ibb_mcp.telemetry`. `nabiz.alerts` and `nabiz.agent.telemetry` remain as the same module objects
  (aliases), so old imports and monkeypatches keep working. Turkish text folding has one home,
  `ibb_mcp.text` (`normalize_tr`, and `fold_tr` where punctuation must survive).
- `scripts/check_architecture.py` enforces the import layers (foundation, sources, domain, services,
  facade, transport, apps), no cycles, the declared third-party set of each package, one definition per
  public name and no private imports, and ratchets module size (400 code lines), class size (250 code
  lines, 15 public methods) and ruff's C901/PLR0912/PLR0913/PLR0915 against
  `scripts/architecture_baseline.json`: what is over the cap may shrink, never grow. It runs in CI and
  `make architecture`; the rules and their reasons are docs/ENGINEERING.md §13 and §14.
- Performance is budgeted by counting, not timing: upstream calls per tool cold and warm, single flight
  and stale-on-error through the real tool path, parses per process, what `import ibb_mcp.server` loads;
  latency only as a wide backstop (`tests/test_performance_budgets.py`, `scripts/perf_report.py`).

### Consequences

- The import test #8 said was owed exists, and fails the build.
- A change that must grow a module over the cap extracts something in the same change or raises the
  baseline entry with its reason in the commit, in front of the owner.
- No layer exception remains. The one the move left, the web app importing `setup_telemetry` through the
  old `nabiz.agent.telemetry` path, was switched to `ibb_mcp.telemetry` in the same batch and its dated
  entry deleted; a new exception needs an entry in `LAYER_EXCEPTIONS`, and a stale one fails the build.
