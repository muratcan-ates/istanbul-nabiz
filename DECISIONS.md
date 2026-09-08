# Architecture decision record

Each entry records a decision that would be expensive to reverse, the situation that forced it, and what
it costs. Decisions are not deleted when they turn out badly — they are superseded by a later entry, so
the reasoning stays readable.

| # | Decision | Status |
|---|---|---|
| [1](#1-azure-data-explorer-free-cluster-for-history-not-fabric-eventhouse-or-azure-sql) | Azure Data Explorer free cluster for history, not Fabric Eventhouse or Azure SQL | Accepted — **gated** on headless ingestion auth |
| [2](#2-the-mcp-server-is-the-product-the-agent-is-its-first-client) | The MCP server is the product; the agent is its first client | Accepted |
| [3](#3-one-shared-collector-and-a-ttl-cache-never-a-per-user-upstream-call) | One shared collector and a TTL cache, never a per-user upstream call | Accepted |
| [4](#4-bus-eta-from-stop-sequence-and-distance-not-machine-learning) | Bus ETA from stop sequence and distance, not machine learning | Accepted |
| [5](#5-the-llm-is-swappable-through-environment-variables) | The LLM is swappable through environment variables | Accepted |
| [6](#6-delta-lake-for-silver-and-gold-rather-than-plain-parquet) | Delta Lake for silver and gold rather than plain Parquet | Accepted |
| [7](#7-bus-number-plates-are-dropped-at-the-parsing-boundary) | Bus number plates are dropped at the parsing boundary | Accepted |
| [8](#8-src-layout-with-two-packages-instead-of-the-packages-layout-in-planmd) | `src/` layout with two packages instead of the `packages/` layout in PLAN.md | Accepted — supersedes PLAN.md §12 |
| [9](#9-pivot-from-nefes-air-quality-early-warning-to-nabız-city-agent) | Pivot from "Nefes" (air-quality early warning) to "Nabız" (city agent) | Accepted |

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
Foundry Local runs on this M1 machine today. **GitHub Models was retired on 30 July 2026**, so the usual
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
