# Threat model

İstanbul Nabız is an unofficial, public, one-person project: an MCP server (`ibb_mcp`) and a city
agent, web UI, collector and alert engine (`nabiz`) over İstanbul Metropolitan Municipality (İBB)
open data. This document names what is worth protecting, where the trust boundaries are, what can go
wrong at each one, and which file or setting stops it. It is written for reviewers, contributors and
the owner, and it is kept honest in one specific way: **every control is marked with its real state
on the date below**, and a control that exists only as a plan is called a plan.

- **Date of this reading:** 2026-09-23.
- **Method:** STRIDE per component (Spoofing, Tampering, Repudiation, Information disclosure, Denial
  of service, Elevation of privilege), plus the OWASP Top 10 for LLM Applications 2025 for the agent
  (<https://genai.owasp.org/llm-top-10/>) and the MCP security best practices
  (<https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices>).
- **Evidence:** the files named in each row, the GitHub REST API (read-only) for repository settings,
  and `git log` for history. Nothing was deployed on this date (`docs/ENGINEERING.md` §9), so every
  Azure control below is a *template setting* in `infra/`, not observed runtime state.
- **Companion documents:** reporting and scope in [`SECURITY.md`](../SECURITY.md); engineering rules
  in [`docs/ENGINEERING.md`](ENGINEERING.md) §7; data handling of the alert engine in
  [`docs/privacy.md`](privacy.md); decisions in [`DECISIONS.md`](../DECISIONS.md).

### Status legend

| Status | Meaning |
|---|---|
| **implemented** | On `main` as pushed to GitHub, or a GitHub setting verified through the API on the date above. |
| **in progress** | Present in the working tree or in a local commit on the date above, not yet on `main`. It becomes *implemented* when it is pushed; until then the public repository does not have it. |
| **owner action** | A setting, decision or account change only the repository owner can make (GitHub, Azure, the workstation). |
| **none yet** | A known gap with no control. Listed so a reviewer aims at it instead of rediscovering it. |

---

## 1. System context

### 1.1 Components

| ID | Component | What it is | Where |
|---|---|---|---|
| C1 | **MCP server** | The product. Parametric, read-only tools over İBB data, served over stdio (local clients) or streamable HTTP (the Azure Container Apps shape, public ingress). | `src/ibb_mcp/server.py`, `infra/modules/containerapps.bicep` |
| C2 | **Web app** | FastAPI service exposing the same tools as GET endpoints, the alert check as one POST, and a static single-page UI. | `src/nabiz/web/` |
| C3 | **City agent + LLM** | A tool loop over the same tools, with a numeric faithfulness check and a deterministic no-model mode. The model is whatever `/chat/completions` endpoint the operator configures. | `src/nabiz/agent/` |
| C4 | **Collector** | The one scheduled reader of İBB. On `main`: Azure Functions timers. In progress: scheduled Container Apps Jobs (DECISIONS #10). Also runnable on a laptop. | `src/nabiz/collector/`, `infra/modules/functions.bicep`, `infra/modules/collectorjobs.bicep` |
| C5 | **Lake and history store** | Blob Storage (bronze snapshots) and an Azure Data Explorer free cluster created outside ARM. | `infra/modules/storage.bicep`, `kql/` |
| C6 | **Alert engine** | Stateless rule evaluation: the client holds the subscription, the server stores nothing. | `src/nabiz/alerts/`, `docs/privacy.md` |
| C7 | **CI** | One GitHub Actions workflow: lint, tests, MCP smoke test, Bicep compile; in progress, a guardrails step and an authorship-gate job. Offline, read-only token, no secrets. | `.github/workflows/ci.yml` |
| C8 | **Supply chain** | PyPI dependencies, GitHub Actions, the `uv` installer, the container base image, and this repository itself as the source users run with `uvx ibb-mcp`. | `pyproject.toml`, `.github/workflows/ci.yml`, `docs/deploy.md` |
| C9 | **Repository identity** | Who the public history says wrote the code, and what personal detail travels with it. | git metadata, tracked files |
| C10 | **Owner's workstation** | Treated as an abstract asset: the machine that holds the credentials, the clone, the laptop collector and the AI coding agents. Its concrete audit is kept privately, not in this repository. | — |

### 1.2 Assets

| ID | Asset | Why it matters |
|---|---|---|
| A1 | İBB's shared gateway and the project's slice of it | The gateway returns HTTP 503 to every consumer after about 15 rapid calls; İETT documents 100 requests/hour (`docs/NABIZ.md` §1.4). Exhausting it hurts every other user of this public data, not only us. |
| A2 | Correctness of every number the product states | The product's claim is "no invented numbers" (`src/nabiz/agent/faithfulness.py`). A wrong number with an İBB citation borrows İBB's authority. |
| A3 | User location and alert subscriptions | Personal data under KVKK (Law No. 6698). The design goal is to hold none of it server-side (`docs/privacy.md` §1). |
| A4 | Owner identity | E-mail address, home-directory paths, machine and account details: things a public repository must not carry. |
| A5 | Azure for Students credit | About $100 of credit (comment in `infra/main.bicep`); when it runs out the subscription is disabled. A dead subscription costs more than a missing feature. |
| A6 | Credentials | GitHub, Azure and LLM credentials on the workstation. None is needed by CI or stored in the repository. |
| A7 | Integrity of `main` and of what users install | Users run this code with their own privileges through their MCP client. |
| A8 | Collected history | The time series İBB does not publish. Once a collection window passes, it cannot be recollected. |

### 1.3 Trust boundaries

```
                   TB1  public internet (untrusted callers)
  MCP clients ──────────────► C1 MCP server (HTTP) ──┐
  Browsers ── HTTPS ────────► C2 web app  ───────────┤   TB2  shared, rate-limited upstream
    (alert subscription      (GET tools,             ├──────────────► İBB gateway
     kept in localStorage)    POST /api/alerts/check)│                (untrusted data)
                                                     │
  C3 agent ── tools in-process ──────────────────────┘
      │ TB3  prompt + tool results leave the process
      ▼
  LLM endpoint (operator's choice; may be on-device)
      ▲ TB4  İBB free text re-enters as model input

  C4 collector (scheduled) ── TB2 ──► İBB gateway
      │ TB5  managed identity (Entra), no keys
      ▼
  C5 Blob lake ──► ADX free cluster ◄── C1 reads with its own managed identity

  C7 CI runner ◄── TB6 ── pull requests from anyone (public repo)
  C10 workstation ── TB7 ──► GitHub, Azure, LLM providers, any synced folder
```

| Boundary | Crossing | Default stance |
|---|---|---|
| TB1 | Anonymous callers to the HTTP endpoints | Untrusted input; public data out; no per-user state kept. |
| TB2 | Our processes to İBB | İBB responses are untrusted data (shape, values and free text); our request rate is a shared resource we must police ourselves. |
| TB3 | Agent to model provider | Only what is needed to answer leaves; the operator chooses the provider. |
| TB4 | Tool results into the model context | Upstream free text is data, never instructions. |
| TB5 | Compute to storage/telemetry | Managed identities and role assignments, no connection-string keys. |
| TB6 | Contributors to CI | Pull requests run with a read-only token and no secrets. |
| TB7 | Workstation to the outside | Credentials in the OS keychain, the clone outside synced folders, no personal detail in tracked files. |

---

## 2. STRIDE by component

### C1 — MCP server (public HTTP endpoint)

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| MCP-1 | S | Anyone can call the endpoint; there is no client identity. | By design for public open data: no per-user state exists to impersonate. An optional API key (`NABIZ_API_KEYS`, compared in constant time, one refusal message for a missing or wrong key) exists and is off by default; whether to require it, or Entra sign-in, before a public launch is a decision, not an oversight. | in progress (optional key) · owner action (require it or not) | `infra/modules/containerapps.bicep` (`external: true`), `src/ibb_mcp/server.py` (`ApiKeyGate`) |
| MCP-2 | T | A tool argument smuggles markup or a query into the upstream request. | Tools are parametric: no URL argument (no SSRF surface), no free-form SQL/KQL. Line codes are checked against `LINE_CODE_RE` and XML-escaped before they enter the SOAP body. | implemented | `src/ibb_mcp/sources/iett.py`, `docs/NABIZ.md` §1.6 |
| MCP-3 | R | A caller who drains the budget cannot be identified afterwards. | Deliberately no client IPs or identities are stored (privacy over attribution). The limiter keeps a salted per-process SHA-256 pseudonym, in memory only (at most `NABIZ_MCP_MAX_CLIENTS` entries), logged only on a refused call; uvicorn's access log is off. Aggregate request telemetry only. | accepted trade-off · in progress (pseudonymous limiter) | `src/ibb_mcp/server.py` (`_pseudonym`, `ToolBudget`), `src/nabiz/web/main.py` (`log_requests`) |
| MCP-4 | I | A tool returns personal data or internals. | The bus number plate is dropped at the parsing boundary and asserted absent by tests; unexpected errors return only the exception type, never a stack trace. | implemented | `src/ibb_mcp/models.py`, DECISIONS #7, `tests/test_models.py`, `tests/test_web.py`, `src/ibb_mcp/server.py` (`_error`) |
| MCP-5 | D | **Budget exhaustion through our server** (see §4). | Shared `PoliteClient`: ≥ 6 s between calls per host, sliding İETT budget of 80/hour; single-flight TTL cache with stale-on-error; `maxReplicas` 1 so replicas cannot multiply the budget. Per-client fairness: every `tools/call` over HTTP is charged to its caller's token bucket at the tool's cold-cache price (`ToolBudget`, `TOOL_COSTS`). A line code İETT's GTFS route list does not know is refused before it spends an İETT call (when the GTFS export is present). | implemented (upstream protection) · in progress (per-client fairness, line-code check) | `src/ibb_mcp/http.py`, `src/ibb_mcp/cache.py`, `src/ibb_mcp/server.py`, `src/ibb_mcp/tools.py` (`_refuse_unknown_line`), `infra/main.bicep` (`mcpMaxReplicas`) |
| MCP-6 | D | Steady traffic keeps a replica warm and spends credit. | See COST-1. | — | §6 |
| MCP-7 | E | A compromised container uses its Azure identity. | User-assigned identity with Storage Blob Data Reader on the lake, AcrPull and Monitoring Metrics Publisher only; no keys in its environment. | implemented (template) | `infra/modules/containerapps.bicep` |
| MCP-8 | S | DNS rebinding lets a web page drive a server running on a developer's machine. | The server binds `127.0.0.1` by default, and the MCP SDK (2.x) enables DNS-rebinding protection automatically for localhost binds. Binding `0.0.0.0` locally removes that protection. | implemented (default bind) | `src/ibb_mcp/server.py` (`build_http_app` passes the bind host); `tests/test_server_security.py::test_a_loopback_bind_keeps_the_sdks_dns_rebinding_protection` |
| MCP-9 | D | A loop of uncharged `initialize` calls fills the SDK's session table (10,000 sessions) and locks every caller out. Measured on 2026-09-23: in the SDK's default stateful mode each `initialize` held one session. | The public transport runs stateless: no session is held per client, and no tool needs one. | in progress | `src/ibb_mcp/server.py` (`stateless_http=True`), `tests/test_server_security.py` |
| MCP-10 | D | One oversized argument stalls the event loop for every caller. Measured on 2026-09-23: the gazetteer resolver took 14.9 s for a 4,000,000-character place name, about 1 ms for 120 characters. | Every free-text parameter carries a `maxLength` in its advertised schema (120 for a name, 16 for a code), counts and horizons a maximum, and the request body is capped at 64 KiB instead of the SDK's 4 MiB. | in progress | `src/ibb_mcp/server.py` (`MAX_NAME_CHARS`, `MAX_REQUEST_BYTES`), `src/nabiz/alerts/schema.py` |

### C2 — Web app

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| WEB-1 | T | İBB free text (stop names, disruption notices) injects script into the page. | Interpolated values pass through the `esc()` HTML-escaping helper. Every response carries a Content-Security-Policy that allows scripts only from the site itself and cdnjs (no inline script; `style-src` keeps `'unsafe-inline'` for the inline widths and colours app.js sets), plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. | implemented (escaping) · in progress (CSP) | `src/nabiz/web/static/app.js`, `src/nabiz/web/main.py` (`SECURITY_HEADERS`), `tests/test_web.py` |
| WEB-2 | I | Place names or coordinates end up in server logs. | The access log writes method and path only, never the query string. Alert subscriptions travel in a POST body, are never logged, and never touch disk; tests capture every log record during an evaluation. | implemented (GET routes, engine tests) · in progress (the POST route) | `src/nabiz/web/main.py`, `tests/test_alerts.py`, `docs/privacy.md` §4 |
| WEB-3 | I | A browser map key is lifted and spent against the subscription. | `NABIZ_MAPS_KEY` reaches every browser by design, so it is treated as public. Azure Maps is off by default and the map falls back to OpenStreetMap tiles; if enabled, use an origin-scoped SAS token or Entra instead of a subscription key. | implemented (off by default) · owner action (if Maps is enabled) | `src/nabiz/web/main.py` (`config_js`), `infra/main.bicep` (`deployMaps`) |
| WEB-4 | E | A foreign origin uses the API from a visitor's browser. | The CORS allow-list is empty by default and GET-only. | implemented | `src/nabiz/web/main.py` (`cors_origins`) |
| WEB-5 | D | An oversized alert subscription makes one request expensive. | At most 5 places and 20 rules per subscription; over MCP every string and list in it also has a length limit; evaluation reads only the shared cache. | in progress | `src/nabiz/alerts/engine.py` (`MAX_PLACES`, `MAX_RULES`), `src/nabiz/alerts/schema.py` |

### C3 — City agent and LLM

| ID | OWASP LLM / STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| AGT-1 | LLM01 Prompt injection · T | İBB free text returned by a tool (a disruption notice, a stop name, a tariff string) carries instructions to the model. | **Blast radius is bounded by construction:** every tool is read-only and parametric; no tool writes, sends, fetches a URL or runs code, so injected text can at most change which public data is read and what the answer says. The loop stops after 4 steps. The agent's system prompt and the MCP server's instructions both tell the model that text inside tool results is data, never instructions. | implemented (bounded agency) · in progress (explicit instruction) | `src/nabiz/agent/agent.py` (`max_steps`), `src/nabiz/agent/system_prompt.md`, `src/ibb_mcp/server.py` (`INSTRUCTIONS`) |
| AGT-2 | LLM06 Excessive agency · E | The agent is talked into an action with side effects. | There are no side-effecting tools to call. | implemented | `src/ibb_mcp/tools.py` |
| AGT-3 | LLM09 Misinformation | The model states a number no tool returned. | Every number in the answer is checked against the raw tool payloads; one repair attempt; a second failure returns the answer flagged `faithfulness.passed = False` with a warning. **Residual:** a number that appears anywhere in upstream text counts as supported, including text an attacker managed to put upstream. The check proves provenance, not truth. | implemented | `src/nabiz/agent/faithfulness.py`, `src/nabiz/agent/agent.py` |
| AGT-4 | LLM02 Sensitive information disclosure · I | A user's typed address, or an alert subscription passed through an MCP tool, reaches a model provider. | Nothing personal is needed to answer. The operator picks the provider, and Foundry Local keeps the conversation on the device. Through an MCP client, whatever the user sends to a tool is also in that client's conversation with *its* model provider, even though this server stores nothing; `docs/privacy.md` §4 says so for the alert tool. | implemented (no server-side storage) · in progress (the client-side flow documented) | `src/nabiz/agent/llm.py`, `docs/privacy.md` |
| AGT-5 | LLM10 Unbounded consumption · D | A question loops the model and spends tokens. | Step cap of 4 plus one repair; no LLM endpoint or key is wired into `infra/`; the deterministic mode needs no model at all. | implemented | `src/nabiz/agent/agent.py`, DECISIONS #5 |
| AGT-6 | LLM07 System prompt leakage | The prompt is extracted. | The prompt is public in this repository and contains no secret. | accepted | `src/nabiz/agent/system_prompt.md` |

### C4 — Collector

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| COL-1 | S/E | The collector exposes a callable surface. | Timer and schedule triggers only; no HTTP trigger. | implemented (Functions) · in progress (Jobs) | `src/nabiz/collector/function_app.py`, `infra/modules/collectorjobs.bicep` |
| COL-2 | D | **Per-process budgets add up.** Each process enforces its own İETT budget, so the deployment's combined ceiling is the sum. The collector jobs plan 66 İETT requests in their peak hour (`python -m nabiz.collector.job --plan`, working tree, 2026-09-23); the MCP server allows itself 80. Together that is up to 146/hour against İETT's documented 100. Whether İBB counts per IP, per service or per client is not documented anywhere in this repository — unverified. | The collector's own spend is fixed by schedule arithmetic and a per-run cap held by tests. The server's 80 is sized for the server alone. | in progress (collector) · none yet (a joint budget) | `src/nabiz/collector/job.py`, `src/ibb_mcp/http.py` |
| COL-3 | I | A plate reaches the lake or ADX. | Dropped at parse; asserted on snapshot rows, on the lake bytes and on the Kusto schema. | implemented | `tests/test_collector.py` (`test_snapshot_fleet_never_carries_a_number_plate`, `test_lake_bytes_contain_no_number_plate`, `test_kusto_defines_no_plate_column`) |
| COL-4 | D | Two collectors (laptop and cloud, or Functions and Jobs) run at once and double the spend. | The Function collector is off by default once Jobs exist; the laptop collector holds a pid lock against a second copy of itself. Nothing prevents a laptop collector and a cloud collector from running together. | in progress · none yet (cross-host) | `infra/main.bicep` (`deployCollectorFunction`), `scripts/supervise_collector.sh` |

### C5 — Lake and history store

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| LAKE-1 | I | Blobs are read anonymously or with a leaked account key. | `allowBlobPublicAccess: false`, `allowSharedKeyAccess` false by default, OAuth by default; access through role assignments to managed identities. | implemented (template) | `infra/modules/storage.bicep` |
| LAKE-2 | D | Collected history disappears. | Bronze lifecycle deletes snapshots after `bronzeRetentionDays` (30 by default) — a volume and cost bound, not a privacy one — so history survives only if ADX holds a copy. The ADX ingestion grant is untested from this subscription. | implemented (template) · owner action (confirm ADX ingestion before relying on bronze expiry) | `infra/main.bicep`, `docs/NABIZ.md` §1.6 |
| LAKE-3 | I | Personal data enters the free cluster, whose terms forbid it. | Plates are gone before the lake; the alert engine writes nothing. | implemented | COL-3, C6 |

### C6 — Alert engine

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| ALR-1 | I | The server keeps users' home and work coordinates. | Stateless evaluation: the subscription lives in the browser's `localStorage` and in the request body only; no database, session or cookie. | implemented (engine) · in progress (HTTP route) | `src/nabiz/alerts/`, `docs/privacy.md` |
| ALR-2 | I | A validation error echoes a coordinate back or into a log. | The engine's refusal names a place key, never a coordinate; the route takes a plain object so the framework's own validation error does not echo input. | in progress | `src/nabiz/web/main.py` (`api_alerts_check`), `tests/test_alerts.py` |
| ALR-3 | D | A per-user alert triggers a per-user upstream call. | Evaluation reads only the shared TTL cache; there is no code path from a subscription to an extra İBB request. | implemented | `docs/privacy.md` §2, DECISIONS #3 |

### C7 — CI

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| CI-1 | E | A workflow gets write access to the repository. | `permissions: contents: read` in the workflow; repository default workflow token is read-only and Actions cannot approve pull requests (API, 2026-09-23). | implemented | `.github/workflows/ci.yml`, repository settings |
| CI-2 | I | A workflow exfiltrates a secret. | No workflow reads `secrets.*`; the repository has 0 Actions secrets, 0 variables and 0 environments (API, 2026-09-23). | implemented | `.github/workflows/ci.yml` |
| CI-3 | T | A fork's pull request runs attacker code with privileges. | Triggered by `pull_request`, not `pull_request_target`: fork code runs with a read-only token and nothing to steal. First-time contributors need approval before their workflows run. | implemented · owner action (optionally require approval for all outside contributors) | `.github/workflows/ci.yml`, repository settings |
| CI-4 | T | A moved action tag or a compromised installer runs in CI. | On `main`, actions are pinned by tag (`@v4`, `@v5`) and `uv` comes from an unpinned `curl \| sh`. The working tree pins every action to a full commit SHA and installs `uv` 0.11.14 from PyPI with `pip --require-hashes` against the wheel hashes in `.github/requirements-uv.txt`, so a changed wheel is refused, not run; no third-party action is added for it. Not yet run on a runner. Impact is limited by CI-1 and CI-2 either way: nothing to steal and nothing deploys. | in progress (not on `main`) | `.github/workflows/ci.yml`, `.github/requirements-uv.txt`, `docs/ENGINEERING.md` §7 (SC-2) |
| CI-5 | D | CI spends İBB's budget. | `NABIZ_OFFLINE=1` for the whole workflow; tests run on recorded fixtures. | implemented | `.github/workflows/ci.yml` |
| CI-6 | T | A privacy or attribution regression merges unnoticed. | `scripts/guardrails.py` encodes the checks in §4 and §5 and runs as a CI step; `scripts/check_authorship.py` checks the identity and message of every pushed or proposed commit in its own CI job. Neither is on `main` yet. | in progress | `scripts/guardrails.py`, `scripts/check_authorship.py`, `.github/workflows/ci.yml` |
| CI-7 | T | History on `main` is force-pushed or the branch deleted. | `main` has no branch protection and no ruleset (API, 2026-09-23). | owner action | repository settings |

### C8 — Supply chain

| ID | STRIDE | Threat | Control | Status | Where |
|---|---|---|---|---|---|
| SC-1 | T/E | **This repository is itself a supply chain.** `uvx ibb-mcp` runs our code with the user's privileges inside their IDE; a compromised owner account or a malicious merged change reaches every user. | Account hardening, branch protection and review are the controls: see CI-7, ID-5 and §7. | owner action | — |
| SC-2 | T | A dependency release or a typosquat executes at install time, on a workstation or in CI. | Dependencies are declared with ranges and not locked. | none yet | `pyproject.toml`, `docs/ENGINEERING.md` §7 |
| SC-3 | I | A known-vulnerable dependency ships unnoticed. | Dependabot alerts and security updates are off (API, 2026-09-23). Alerts do not open pull requests, so turning them on adds no bot contributor. | owner action | repository settings, `docs/ENGINEERING.md` §7 (SC-3) |
| SC-4 | I | A secret is pushed. | GitHub secret scanning and push protection are on (API, 2026-09-23); guardrail `no-secrets`; `.env` and `.azure/` are gitignored. | implemented (GitHub, `.gitignore`) · in progress (guardrail) | `.gitignore`, `scripts/guardrails.py` |
| SC-5 | T | The container base image changes under us. | The Dockerfile is at the repository root; its base image `python:3.12-slim` is not yet pinned by digest (`docs/deploy.md` §5). | none yet | `Dockerfile` |
| SC-6 | T | The map library served from a public CDN is altered and runs in every visitor's page. | The URL pins an exact version (MapLibre GL 4.7.1) and loads with `crossorigin="anonymous"`, but carries no Subresource Integrity hash, so a changed file would still execute. | none yet | `src/nabiz/web/static/index.html` |

---

## 3. LLM-specific threats in one place

The agent reads İstanbul's public data; it does not act on the world. That single property is the
main control, and the table in C3 is organised around keeping it true.

1. **Treat upstream text as untrusted.** İBB free-text fields are written by people and systems we do
   not control. They reach the model as tool results (TB4). The right mitigations, in order of
   strength: keep every tool read-only and parametric (implemented); keep the step budget small
   (implemented); tell the model explicitly that tool output is data (in progress — a sentence in
   `src/nabiz/agent/system_prompt.md` and in the MCP server's `INSTRUCTIONS`); and never add a tool
   that takes a URL, sends a message or writes anywhere without re-reading this section.
2. **Excessive agency.** Adding a side-effecting tool (notifications, bookings, anything that writes)
   changes the threat model; it needs a confirmation step outside the model and its own row here.
3. **Numeric hallucination.** The faithfulness check is the project's core promise and it is
   implemented. Its limit is stated in AGT-3: it proves a number came from the evidence, not that the
   evidence is right. Stale data is surfaced through provenance (`age`, `stale`), not hidden.
4. **Consumption.** No LLM spend exists in the deployed shape; see COST-6.

---

## 4. Privacy and KVKK

| Rule | How it is enforced | Status | Where |
|---|---|---|---|
| Bus number plates never leave the parser. | `BusPosition.from_fleet_raw` drops the field; tests assert it absent from models, web output, snapshots, lake bytes and the Kusto schema; guardrail `no-plate` scans source. | implemented (code and tests) · in progress (guardrail) | DECISIONS #7, `src/ibb_mcp/models.py`, `tests/`, `scripts/guardrails.py` |
| Recorded test fixtures hold no real plate. | The fleet fixtures on `main` still carry plate values as recorded from the live feed (60 plate-shaped values in `tests/fixtures/iett_fleet.json`, 21 in `tests/fixtures/iett_fleet.soap.xml`, counted 2026-09-23). The capture script now swaps every plate for a synthetic one before writing, the fixtures are rewritten, and guardrail `fixture-plates-synthetic` plus a test hold that; since 2026-09-23 the guardrail also fails a plate-shaped example with a real province code anywhere else in the tree, after one recorded plate outlived the scrub as the eval harness's example. Git history keeps the earlier version. | in progress · owner action (history, see §5.3) | `scripts/capture_fixtures.py`, `tests/test_models.py`, `scripts/guardrails.py` |
| User location is never stored server-side. | The alert engine is a stateless evaluator; coordinates live in the browser and in one request body; tests assert no coordinate reaches a log record or disk. | implemented (engine) · in progress (HTTP route) | `docs/privacy.md`, `tests/test_alerts.py` |
| No server log carries a location or a place query. | Access log records method and path, not the query string; the alert summary line carries counts only. | implemented | `src/nabiz/web/main.py`, `src/nabiz/alerts/engine.py` |
| Data minimisation towards third parties. | No analytics or tracking script in the UI. The page does load the map library from cdnjs and map tiles from OpenStreetMap, so those two providers see a visitor's IP address and the map area viewed, as with any web map; neither receives a query, a subscription or an identifier from us. | implemented (no tracking) · accepted (map providers) | `src/nabiz/web/static/index.html` |

**Budget exhaustion as an availability attack.** The HTTP endpoints are the only way an outsider
reaches İBB through us. The shared client guarantees İBB never sees more than our budget, and the cache
answers repeat questions for free. What it does not guarantee is fairness: one client asking for many
*distinct* things (80 different line codes in an hour, say) spends the whole İETT budget, after which
every user gets `rate_limited` until the sliding window frees a slot, and the 6-second per-host gate
queues every other İBB source behind the flood. Two cheap mitigations, both **in progress** (working
tree, 2026-09-23):

1. A line code is resolved against the local GTFS route index before any upstream call, so a code that
   does not exist costs nothing (`iett_line_buses` and `iett_next_arrivals`, `Nabiz._refuse_unknown_line`; without a GTFS export
   the check is skipped and the call goes ahead as before).
2. A per-client token bucket on the MCP HTTP transport (`ToolBudget`), in memory and keyed by a salted
   pseudonym. It charges every call its tool's worst-case cold-cache price, not only cache misses, so a
   cached answer still costs tokens. The web app's GET routes have no per-client bucket yet.

Sizing matters as well: with the collector jobs deployed (COL-2), the server's İETT budget should be
100 minus the collector's planned peak minus a margin, not 80.

---

## 5. Repository identity

The repository is public and its history is permanent. Three kinds of personal trace can leak through
it, plus one requirement the owner states as a rule: an AI assistant must never appear as an author,
co-author or contributor.

### 5.1 Threats and controls

| ID | Threat | Control | Status | Where |
|---|---|---|---|---|
| ID-1 | An AI assistant is credited: a co-author trailer or an assistant footer in a commit or pull request, a bot account as author, or a GitHub App that commits. Any of these makes the assistant show up on the contributors graph. | Repository-level assistant settings with empty commit and PR attribution, and a VS Code workspace setting that keeps Copilot's co-author trailer off (`git.addAICoAuthor`); a tracked pre-push hook that runs the commit gate before anything is public, once the owner runs `make hooks`; guardrail `no-ai-attribution` over tracked files; a commit gate `scripts/check_authorship.py` that fails any pushed or proposed commit whose author is not the owner's noreply identity, whose author or committer looks like an assistant or a bot, or whose message carries an assistant trailer or footer (run in CI as its own job; it checks only new commits, not the 19 older ones in ID-2); the rule stated for agents in `AGENTS.md` §2 and for people in `CONTRIBUTING.md`; no GitHub App or Action that commits, and no Dependabot version-update pull requests. **Measured on 2026-09-23:** zero assistant co-author trailers in this repository's history, and the contributors API lists one contributor, the owner. | in progress (settings file, guardrail, commit gate, `AGENTS.md`) · owner action (user-level assistant settings on each machine) | `.claude/settings.json`, `.vscode/settings.json`, `.githooks/pre-push`, `scripts/guardrails.py`, `scripts/check_authorship.py`, `AGENTS.md`, `CONTRIBUTING.md` |
| ID-2 | A personal e-mail address in commit metadata. 19 of the 20 commits on `main` carry one, as both author and committer. | This clone's git identity uses the GitHub noreply address from 2026-09-23 (first such commit is local and not yet pushed). GitHub's *Keep my email addresses private* and *Block command line pushes that expose my email* stop a recurrence at push time. The existing 19 commits change only if history is rewritten (§5.3). | in progress (local identity) · owner action (GitHub settings; history decision) | git config, <https://github.com/settings/emails> |
| ID-3 | Personal or machine-specific detail in tracked files. Earlier versions of several tracked files carried such detail. | Scrubbed in the working tree; the collector log is untracked (it is already covered by `.gitignore`); guardrail `no-personal-data` allows only the noreply addresses and no home path. History is unchanged (§5.3). | in progress · owner action (history) | `scripts/guardrails.py`, `.gitignore` |
| ID-4 | Real upstream plates in public test fixtures. | See §4, second row. | in progress | `scripts/capture_fixtures.py` |
| ID-5 | Someone authors commits under the owner's noreply address (git does not verify authorship), or a stolen credential pushes to `main`. | Commit signing with *vigilant mode* marks unsigned commits as unverified; branch protection limits what one credential can do; account two-factor authentication. | owner action | <https://github.com/settings/keys>, repository settings |

### 5.2 What a reviewer can run

```bash
.venv/bin/python scripts/guardrails.py --only no-personal-data,no-ai-attribution,no-secrets,no-plate,fixture-plates-synthetic
git log --format='%ae%n%ce' | sort | uniq -c        # which identities the history carries
```

### 5.3 The history-rewrite option (owner's decision)

Rewriting author and committer e-mail on the 19 commits (for example with `git filter-repo
--mailmap`) removes the address from the commit objects on GitHub. It also changes every commit SHA
from the first rewritten commit onward, which means a force-push to `main`; every other clone, worktree
and branch must be rebased onto the new history; SHAs quoted in documents (this repository quotes
several) stop resolving; and anything already copied — forks, caches, mirrors, search engines — keeps
the old objects. A `.mailmap` file alone changes only how local tools display names; it does not
remove the address from the commits. Rewriting reduces future exposure; it cannot recall past
exposure. This document records the option and its cost; it does not recommend doing it silently.

---

## 6. Cost threats and guards

Azure for Students has no card attached; when the credit is exhausted the subscription is disabled
rather than billed. The practical risk is therefore *losing the subscription early*, not a surprise
invoice — unless the subscription is ever upgraded to pay-as-you-go, which changes every row below.

| ID | What could spend | Guard | Status | Where |
|---|---|---|---|---|
| COST-1 | **MCP Container App kept warm by traffic.** `minReplicas` 0, `maxReplicas` 1, 0.5 vCPU / 1 GiB. The monthly free grant quoted in the template is 180,000 vCPU-seconds and 360,000 GiB-seconds; one replica warm for a 30-day month is 0.5 × 2,592,000 = 1,296,000 vCPU-seconds, about 7.2 times the grant (arithmetic on the template's numbers). Steady outside traffic can therefore move the app from free to paid-from-credit. | Scale to zero, one replica ceiling. An Azure cost budget with alerts would give warning; none exists in `infra/`. | implemented (scale bounds) · owner action (budget alert) | `infra/modules/containerapps.bicep`, `infra/main.bicep` |
| COST-2 | **Container registry.** Basic is about $0.167/day, "the single largest line item in this template". | `deployContainerRegistry=false` with a pinned public image avoids it. | implemented (switch) · owner action (choice) | `infra/modules/containerapps.bicep` |
| COST-3 | **Collector.** Functions Flex Consumption (on `main`): timers only, scale to zero, 512 MB; `maximumInstanceCount` 40 is the platform minimum, the collector uses one. Container Apps Jobs (in progress): 0.25 vCPU per execution, one replica per execution, `replicaTimeout` 170–900 s. If every execution ran to its timeout, the five schedules would use 135,000 s/day, about 1,012,500 vCPU-seconds a month (arithmetic on `collectorJobSchedules`); measured laptop tick times are far shorter (lines median 12.1 s against a 170 s timeout, per `src/nabiz/collector/job.py`). A hung job is the cost risk. | A per-run deadline stops reading before the timeout; jobs deploy only once a real image exists, never a placeholder that would run to timeout every tick. | implemented (Functions) · in progress (Jobs) | `infra/modules/functions.bicep`, `infra/modules/collectorjobs.bicep`, `src/nabiz/collector/job.py` |
| COST-4 | **Log ingestion.** A trace loop floods Log Analytics. | Daily cap 0.16 GB and 30-day retention. Until 2026-09-23 the cap was 0.5 GB/day, which allowed 15.5 GB in a 31-day month against the 5 GB/month grant (about $31 at $2.99/GB); the default is now 5 GB over 31 days, so a cap hit every day stays inside the grant, and `tests/test_infra.py` holds both defaults to that. | implemented | `infra/modules/monitoring.bicep`, `infra/main.bicep` |
| COST-5 | **Azure Maps key abuse.** | Off by default; key treated as public if enabled (WEB-3). | implemented · owner action | `infra/modules/maps.bicep` |
| COST-6 | **LLM tokens.** | No LLM endpoint or key in `infra/`; the agent runs locally or deterministically; step cap (AGT-5). | implemented | `infra/`, `src/nabiz/agent/` |
| COST-7 | **Always-on services that bill idle.** Azure AI Search Basic (about $2.42/day idle), Stream Analytics, Data Factory data flows, Marketplace items. | Deliberately not provisioned. | implemented | `infra/main.bicep` header |
| COST-8 | **Storage growth.** | Standard_LRS; bronze lifecycle expiry (LAKE-2). | implemented | `infra/modules/storage.bicep` |
| COST-9 | **GitHub Actions minutes.** | Public repository on standard runners; job timeouts 15 and 10 minutes; no scheduled workflows; no workflow calls a paid API or reads a secret. | implemented | `.github/workflows/ci.yml` |
| COST-10 | **ADX free cluster.** | Created outside ARM, no subscription billing; its limits cap it instead. | implemented | DECISIONS #1 |

---

## 7. Residual risks and owner actions

Ordered by what the owner can close fastest for the most risk removed.

| # | Risk | Action | Who | Where |
|---|---|---|---|---|
| 1 | Personal e-mail keeps entering history from another machine or tool. | Turn on *Keep my email addresses private* and *Block command line pushes that expose my email*. | owner | <https://github.com/settings/emails> |
| 2 | `main` can be force-pushed or deleted by any credential with push access (CI-7, SC-1). | Add a ruleset on `main`: block force pushes and deletion; optionally require the CI check. | owner | repository *Settings → Rules → Rulesets* |
| 3 | Vulnerable dependencies go unnoticed (SC-3). | Turn on Dependabot alerts. Keep version-update pull requests off; apply fixes by hand so no bot appears as a contributor. | owner | repository *Settings → Code security* |
| 4 | Vulnerability reports have no private channel. | Enable private vulnerability reporting (`SECURITY.md`). | owner | repository *Settings → Code security* |
| 5 | Upstream free text can instruct the model (AGT-1). | Done in the working tree (2026-09-23): one sentence in `src/nabiz/agent/system_prompt.md` and in `INSTRUCTIONS` in `src/ibb_mcp/server.py`. Closes when pushed. | owner (push) | — |
| 6 | Non-existent line codes and one busy client drain the İETT budget (MCP-5). | Done in the working tree for the MCP transport (line-code check, per-caller bucket). The web app's GET routes still have no per-client bucket. | owner (push) · lane (web app) | `src/ibb_mcp/tools.py`, `src/ibb_mcp/server.py`, `src/nabiz/web/main.py` |
| 7 | Server and collector budgets add up past İETT's documented limit (COL-2). | Size the server's İETT budget as 100 minus the collector's planned peak minus a margin once the jobs are deployed. | owner decision, then lane | `src/ibb_mcp/http.py` |
| 8 | Guardrails and the authorship gate do not protect `main` until they are on it (CI-6). | Commit and push the in-progress CI changes; then make the CI jobs required checks in the ruleset from row 2. | owner | `.github/workflows/ci.yml` |
| 9 | Credit exhaustion is noticed only when the subscription stops. | Create a cost budget with e-mail alerts at 50/80/100 % of the credit. | owner | Azure portal → Cost Management → Budgets |
| 10 | Dependencies are not locked (SC-2); action pinning is not on `main` yet (CI-4). | Add a lockfile; push the SHA-pinned workflow. | lane | `pyproject.toml`, `.github/workflows/ci.yml` |
| 11 | No integrity hash on the CDN script (SC-6); the CSP (WEB-1) is in the working tree. | Add an `integrity` attribute to both MapLibre 4.7.1 tags, using the SRI value cdnjs publishes for those exact files. | lane (needs a network read of cdnjs) | `src/nabiz/web/static/index.html` |
| 12 | Old personal detail and recorded plates remain in git history (ID-2, ID-3, ID-4). | Decide on §5.3. Doing nothing is a legitimate choice once the tree is clean and recurrence is blocked. | owner decision | — |
| 13 | Unsigned commits (ID-5). | Optional: SSH commit signing and vigilant mode. | owner | <https://github.com/settings/keys> |
| 14 | The workstation (C10) is the root of every credential above. | Full-disk encryption, OS firewall, credentials only in the OS keychain, no long-lived tokens in shell history, the clone outside synced folders, an encrypted local backup of collected data. Audited privately on 2026-09-23. | owner | — |

## 8. Keeping this current

Update the affected row in the same commit that changes a control, and re-read §3 before adding any
tool with a side effect or any tool that takes a URL. The statuses above are a snapshot of 2026-09-23;
anything marked *in progress* should be flipped to *implemented* when it reaches `main`.
