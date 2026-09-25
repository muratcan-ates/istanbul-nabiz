# Using `ibb-mcp` from your own agent

`ibb-mcp` is a plain [Model Context Protocol](https://modelcontextprotocol.io) server over İstanbul's live
open data: parking occupancy, bus positions and arrivals, metro disruptions and station accessibility, the
city traffic index, and air quality. On top of those it answers three things İBB does not publish, derived by
this project: a travel-mode comparison, measured bus-line regularity, and stateless alert checks. Point any
MCP client at it and those become tools your agent can call.

Every result carries a **provenance stamp** — source URL, observation time, and whether the read came from
a stale cache — so an agent using this server can cite what it says and state how old the data is.

> **Not an official İBB service.** Independent student project; see [../NOTICE.md](../NOTICE.md).
> Data: İBB Open Data Portal, İBB Open Data Licence (CC BY 4.0). If you ship something built on this,
> carry that attribution through to your users.

---

## Status

| | |
|---|---|
| Tool implementations (all 17) | **working** — `src/ibb_mcp/tools.py` |
| MCP server entry point (`src/ibb_mcp/server.py`) over **stdio** | **working** — `initialize`, `tools/list` (17) and `tools/call` verified against a real MCP client (`tests/test_mcp_integration.py`) |
| The same entry point over **streamable HTTP** (`--transport http`) | **working locally** — stateless transport, per-caller rate budget, optional API key, closed CORS and `GET /healthz`, exercised over ASGI by `tests/test_server_security.py`; not deployed |
| Hosted HTTP endpoint on Azure Container Apps | **planned**, Day 3 |
| PyPI release (`uvx ibb-mcp`) | **planned** — roadmap, after delivery |
| MCP resources | **partial** — `ibb://attribution` is served today; `ibb://parks`, `ibb://lines`, `ibb://stations`, `ibb://aq-stations` and the `nabiz-system` prompt are **planned** |
| Copilot Studio connection | **planned** — roadmap, depends on tenant permissions |

The stdio configuration below works today against a local checkout. Where a section is marked *planned* —
the hosted URL, `uvx`, the reference resources — the JSON is the contract being built against, but there is
nothing listening yet; that is the honest state of a Day-0 repository.

---

## Install

### Option A — from a checkout (works today: both the stdio server and the Python API)

```bash
git clone https://github.com/muratcan-ates/istanbul-nabiz.git
cd istanbul-nabiz
uv venv -p 3.12 .venv && source .venv/bin/activate
uv pip install -e .
```

This gives you an absolute interpreter path — `<repo>/.venv/bin/python` — which is what desktop MCP
clients need, since they start the server without your shell's environment.

### Option B — `uvx` (planned, after the PyPI release)

```bash
uvx ibb-mcp            # once published
uvx --from git+https://github.com/muratcan-ates/istanbul-nabiz ibb-mcp   # before then
```

`uvx` fetches into a throwaway environment, so nothing is installed system-wide.

---

## VS Code / GitHub Copilot agent mode

Create `.mcp.json` in your workspace (or add the entry to your user-level MCP configuration), then open
Copilot Chat, switch to **Agent** mode, and the tools appear in the tool picker.

**stdio, from a local checkout:**

```json
{
  "servers": {
    "istanbul-nabiz": {
      "type": "stdio",
      "command": "/absolute/path/to/istanbul-nabiz/.venv/bin/python",
      "args": ["-m", "ibb_mcp.server"],
      "env": {
        "NABIZ_GTFS_DIR": "/absolute/path/to/istanbul-nabiz/data/reference/gtfs"
      }
    }
  }
}
```

**stdio, via `uvx`** (after the PyPI release):

```json
{
  "servers": {
    "istanbul-nabiz": {
      "type": "stdio",
      "command": "uvx",
      "args": ["ibb-mcp"]
    }
  }
}
```

**Hosted HTTP endpoint** (planned — streamable HTTP on Azure Container Apps):

```json
{
  "inputs": [
    {
      "id": "nabiz-key",
      "type": "promptString",
      "description": "İstanbul Nabız API key (optional)",
      "password": true
    }
  ],
  "servers": {
    "istanbul-nabiz": {
      "type": "http",
      "url": "https://<container-app>.azurecontainerapps.io/mcp",
      "headers": { "X-API-Key": "${input:nabiz-key}" }
    }
  }
}
```

The data is public and the key is optional. Every caller is rate-limited by tool price either way; with keys
configured, the key rather than the address identifies a caller's budget. It exists to protect the shared
upstream budget, not to gate access.

Try it with: *"Which İSPARK car parks near Taksim have space right now, and what do they charge?"*

---

## Claude Desktop

Edit `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`), then restart Claude Desktop.

```json
{
  "mcpServers": {
    "istanbul-nabiz": {
      "command": "/absolute/path/to/istanbul-nabiz/.venv/bin/python",
      "args": ["-m", "ibb_mcp.server"],
      "env": {
        "NABIZ_GTFS_DIR": "/absolute/path/to/istanbul-nabiz/data/reference/gtfs"
      }
    }
  }
}
```

Use absolute paths for both the interpreter and the directories: the desktop app does not inherit your
shell `PATH`, and a bare `python` will usually resolve to the wrong interpreter or none at all.

## Claude Code

```bash
# stdio, from a checkout
claude mcp add istanbul-nabiz -- /absolute/path/to/istanbul-nabiz/.venv/bin/python -m ibb_mcp.server

# hosted HTTP endpoint (planned)
claude mcp add --transport http istanbul-nabiz https://<container-app>.azurecontainerapps.io/mcp
```

`claude mcp list` shows what is connected; a project-scoped server can also be committed as `.mcp.json`
in the repository root, using the same shape as the VS Code example above.

## Copilot Studio — roadmap

Copilot Studio can consume an MCP server over streamable HTTP as a custom connector, which would make the
same tools available to a Microsoft 365 agent with no extra code. It is deliberately **not** on the
critical path: it depends on tenant permissions that are not ours to grant, and the same server already
demonstrates the point through VS Code Copilot. It will be documented here once the hosted endpoint exists
and a tenant is available to test in.

---

## Tools

All seventeen tools are implemented in `src/ibb_mcp/tools.py` and registered in `src/ibb_mcp/server.py`: the
twelve of PLAN.md §5, plus `plan_journey`, `line_reliability`, `check_alerts`, `metro_equipment_status` and `ibb_services_search`. Parameters marked with a
default are optional. Every tool answers with the same JSON envelope:
`{ data, provenance: { source, source_url, reported_at, observed_at, age, age_seconds, stale, license }, note }`.
A failure is an envelope too — `{ error, message, advice }` with `error` one of `bad_request`,
`rate_limited` (with `retry_after_seconds` when the server's own per-caller budget refused the call),
`upstream_unavailable`, `reference_data_missing` (a local reference file such as the GTFS export is absent;
the message names no path) or `internal_error` — never a stack trace. Free-text parameters carry a
`maxLength` in the advertised schema (120 characters for a name, 16 for a code) and `limit` and
`horizon_hours` a maximum, so an oversized argument is refused before the tool runs. Arguments that do not
match the advertised JSON schema (a `check_alerts` rule of an unknown `kind`, say) are rejected by the SDK
before the tool runs, as an MCP tool error.

| Tool | Parameters | Returns | Upstream · cache TTL |
|---|---|---|---|
| `places_resolve` | `query` *(str)*, `limit=5` | matching places with `lat`, `lon`, `kind`, `district` | local gazetteer (276 entries) · static |
| `ispark_find_parking` | `place` *(str)* **or** `lat`+`lon`, `radius_km=1.5`, `min_free=1`, `open_now=true` (plus `with_tariff=true` on the Python façade only) | up to 5 car parks: name, free spaces / capacity, type (covered / open / on-street), tariff text as published, distance, `updateDate` | İSPARK `Park` + `ParkDetay` · 5 min |
| `ispark_typical_occupancy` | `park_id` *(int)*, `weekday=today` *(0 = Monday … 6 = Sunday)*, `hour=now` *(0–23, İstanbul)*; other values are refused | median occupancy %, p25/p75, sample count, distinct days — or `available: false` with the reason (fewer than 3 samples, or all of them from one day) | `data/reference/occupancy_profile.json`, built by `scripts/build_profiles.py` from the collector's snapshots; `reported_at` is the newest snapshot in it |
| `iett_stops_search` | `query` *(str)*, `limit=8` | stops: `stop_code`, `stop_id`, name, `lat`, `lon` | GTFS (15 390 rows in the export, 15 386 placeable) · static |
| `iett_line_buses` | `line_code` *(str, e.g. `"500T"`)*, `direction=None` | vehicles on the line: door number, direction, nearest stop, last position time; plus the directions currently running. A code İETT's GTFS route list does not know is refused before it spends an İETT request (when the GTFS export is present) | `GetHatOtoKonum_json` · 60 s |
| `iett_next_arrivals` | `line_code` *(str)*, `stop` *(stop code or stop name)*, `limit=3` | estimated arrivals: minutes, stops away, `method` (`stop_sequence` / `distance` / `schedule`), confidence, plus `diagnostics` (which per-stop rate was used and why: `rate_mode`, `rate_source`, `rate_reason`, `seconds_per_stop`; and how the stop was chosen, `stop_resolution`) and an explicit estimate disclaimer. The rate is the untuned 120 s/stop unless the server runs with `NABIZ_ETA_PROFILE_MODE=calibrated` (DECISIONS #18). A stop *name* resolves to the first matching stop the line actually calls at; a stop the line never calls at is refused with the lines that do. A line code İETT's GTFS route list does not know is refused before any İETT request (when the GTFS export is present) | live positions + GTFS order + timetable |
| `metro_status` | `line=None` *(e.g. `"M4"`)* | live disruption notices per line; an empty result means "no disruption reported", stated as such | `GetServiceStatuses` · 5 min |
| `metro_station_info` | `name` *(str)* | line, order on the line, coordinates, and accessibility: lift, escalator count, baby room, WC, prayer room | `GetStations` · 1 day |
| `metro_equipment_status` | `station=None`, `line=None` *(e.g. `"M2"`)*, `group=None` *(`"Asansör"`, `"Yürüyen Merdiven"` or `"Yürüyen Bant"`; typed without Turkish letters is fine)* | every lift, escalator and moving walkway Metro İstanbul records as unusable: code, line, station, İBB's type (Arıza, Revizyon, Çalıştırılmıyor; an unknown type is kept as `unknown`), `ibb_date` (İBB's recorded date: its meaning is undocumented, never a return date), `card_status`, `mode` (`live` or `recorded`), `stale`, uncertainty codes (`date_semantics_unknown`, `summary_detail_mismatch`, ...), the summary beside the detail count per group, and with `station` the station's lift state (`working` means only "no fault in İBB's record"). No recording offline: `available: false`, `card_status: unverified` | `GetFaultyEquipmentDetails` (POST per group) + `GetFaultyEquipments` + `GetStations` · 5 min |
| `traffic_index` | `window="now"` \| `"24h"` | `now`: index 1–99 with a plain-language description, and `typical`: the index against the median of the same İstanbul weekday and hour over İBB's last 28 days (`typical_index`, `delta`, `band`, `samples`, Turkish `description`, and its own `provenance` with the `/28/H` source URL and `age_seconds`, because it comes from a different read than the envelope's; `available: false` when the cell has fewer than 3 samples or the history cannot be read). `24h`: hourly history plus a comparison with the same hour yesterday. A missing reading is `null`, never 0 | traffic index · 5 min; history `/28/H`, rebuilt every 6 h |
| `air_quality_now` | `place` *(str)* | nearest of the 28 stations, latest hourly PM10 / SO2 / O3 / NO2 / CO, published AQI with its band, health disclaimer | `GetAQIByStationId` · 30 min |
| `air_quality_forecast` | `place` *(str)*, `horizon_hours=6` *(at most 24, larger values are refused; keep it ≤ 6 — beyond that the baseline just repeats yesterday)* | hourly PM10 outlook, the cleanest upcoming window, and a flag saying the current method is a seasonal-naive baseline | 48 h of history + baseline model |
| `city_freshness` | — | per source: the data's own age (`data_age_seconds`, from the source's timestamp `reported_at_utc` when it states one), the age of the last successful read (`age_seconds`), health, hit/miss/stale counters; remaining request budget; attribution text | in-process cache |
| `plan_journey` | `origin` *(str)* **or** `origin_lat`+`origin_lon`; `destination` *(str)* **or** `destination_lat`+`destination_lon` *(degrees, WGS84, inside İstanbul)* | a **comparison, not navigation**: per mode (drive, metro, one bus line, walk) total minutes, legs, a 0–100 comfort score, confidence, and every assumption with its value and unit; the metro option follows the rail graph line by line (one leg per line ridden and per transfer; the Bosphorus only through the Marmaray tube); `detail.other_direct_lines` names other single-line buses with stop counts and no minutes; `readings` includes `traffic_typical`; `unavailable_options` names each mode that could not be costed and why (no single bus line, too far to walk, no pedestrian Bosphorus crossing, no GTFS); the disclaimer travels in `data` | traffic index, İSPARK, metro stations and notices, İETT timetable (all through the shared cache) + GTFS stop sequences for the bus option + traffic history `/28/H` (every 6 h); `observed_at` is the oldest live input |
| `line_reliability` | `line_code` *(str, e.g. `"500T"`)*, `hour=now` *(0–23, İstanbul)* | measured **history**, not live: median headway (min), headway cv and its label, samples, vehicles, days, stop-capture rate and the cv a perfectly regular line would show at that rate, the observation window — both numbers are upper bounds. `available: false` with the reason when the cell is too thin or the line was never watched | `data/reference/line_reliability.json`, built by `scripts/reliability_report.py` from the collector's vehicle snapshots; `reported_at` is the last observation |
| `check_alerts` | `subscription` *(object)*: `places[]` `{key, label, lat, lon}`, `rules[]` — one of `metro_disruption` `{lines}`, `parking_filling` `{park_ids, threshold_pct}`, `air_quality` `{place, aqi_threshold}`, `traffic` `{threshold_index}`, `bus_bunching` `{line}`, `lift_outage` `{stations, lines, equipment}` (for example `{"kind": "lift_outage", "stations": ["Kartal"], "lines": ["M4"], "equipment": ["elevator"]}`; `equipment` defaults to `["elevator"]` and also takes `escalator`, `moving_walkway`), each with an optional `cooldown_seconds` — and `muted_keys[]` | alerts in Turkish and English with severity, a `dedupe_key`, `cooldown_seconds` and a citation (value + provenance) for every number; sources that could not be read; the cooldown policy and a privacy summary. **Evaluated in memory for this one request and never stored or logged** ([privacy.md](privacy.md)) | only the sources the rules need: metro notices, the İSPARK list, the nearest air-quality station, the traffic index, the line-reliability table, Metro İstanbul's equipment records (summary, one detail read per equipment type, the station list) |
| `ibb_services_search` | `query` *(str, at most 200 characters)*, `limit=5` *(1–10)* | hits from a **local index** of reviewed public-service pages: quote, link, page title, `fetched_at`, plus `evidence.level`; no index on the server, or no verifiable match, answers with `note` and no hits (`evidence.level: index_missing` when the index is absent) | none from İBB: the SQLite index `NABIZ_KNOWLEDGE_DB` (default `data/knowledge/knowledge.db`, built by the owner with `scripts/knowledge_ingest.py`); an optional query embedding goes to the configured model endpoint, never offline |

Two parameters read differently from the sketch in PLAN.md §5, and the wider form was kept because it is
what people actually type:

- `iett_next_arrivals(stop=…)` accepts a **stop code or a stop name**, not only the `stop_id` of the
  original sketch — a numeric argument is looked up as a code, anything else is searched by name.
- `air_quality_now(place=…)` and `air_quality_forecast(place=…)` take a **place name** (district,
  neighbourhood, landmark or station) and resolve it to the nearest of the 28 stations, rather than
  requiring a station GUID.

Three things about the derived tools are easy to get wrong when relaying them:

- `plan_journey` never produces directions and never invents a bus transfer; a rail transfer exists only where
  two platforms are within walking distance ([route-advisor.md](route-advisor.md) §4). A bus option exists only when one
  İETT line passes a stop near each end in the right order; its ride time uses the same per-stop rate as
  `iett_next_arrivals`, the untuned 120 s/stop by default, and its `bus_seconds_per_stop` assumption says
  which rate it is and why. Only in the calibrated mode is the fitted rate used, which absorbs dwell and
  detection lag, so on a long ride it is an upper bound and the assumption text then says so.
- `line_reliability` and `ispark_typical_occupancy` describe the window the collector watched, stated in
  the result. They are not "always", and a thin cell refuses rather than extrapolating from a neighbour.
- `check_alerts` holds no state. "Subscribing" means the client keeps the subscription and sends it with
  each check; the client, not the server, suppresses repeats using `dedupe_key` and `cooldown_seconds`.

### Resources and prompt

One resource is served today: **`ibb://attribution`**, the İBB source and licence notice in Turkish and
English, so a client can surface the attribution without calling a tool.

Still **planned**: `ibb://parks`, `ibb://lines`, `ibb://stations` and `ibb://aq-stations`, which will
expose the reference lists for clients that browse rather than call, and the `nabiz-system` prompt
carrying the TR/EN answering rules (cite every number, always state data age, never guarantee an
arrival).

### Configuration

| Variable | Default | Effect |
|---|---|---|
| `NABIZ_OFFLINE` | unset | `1` / `true` reads recorded fixtures instead of the network — reproducible demos, no upstream traffic. `ibb-mcp --offline` does the same thing from the command line |
| `NABIZ_GTFS_DIR` | `data/reference/gtfs` | where `stops.csv` and `routes.csv` live (they are not committed) |
| `NABIZ_PLACES_CSV` | `data/reference/places.csv` | the gazetteer behind `places_resolve` |
| `NABIZ_FIXTURES_DIR` | `tests/fixtures` | fixture directory used by offline mode |
| `NABIZ_RADIUS_KM` | `1.5` | default search radius for parking |
| `NABIZ_MAX_RESULTS` | `5` | default result cap |
| `NABIZ_OCCUPANCY_PROFILE` | `occupancy_profile.json` beside `NABIZ_PLACES_CSV` | the table behind `ispark_typical_occupancy` |
| `NABIZ_RELIABILITY_TABLE` | `data/reference/line_reliability.json` | the table behind `line_reliability` and the `bus_bunching` alert |
| `NABIZ_ETA_PROFILE_MODE` | `default` | which per-stop rate arrival estimates use: `default` serves the untuned 120 s/stop, the estimator with the better held-out score (on 523 predictions at stops the fit never saw: 10.18 min MAE for 120 s/stop, 35.82 for the fitted rates, `eval/results/eta.md`); `calibrated` serves the fitted profile below, for research only. Any other value serves the default and says so in `rate_reason` |
| `NABIZ_ETA_PROFILE` | `data/reference/eta_profile.json` | the fitted seconds-per-stop rates, read only when `NABIZ_ETA_PROFILE_MODE=calibrated` (by `iett_next_arrivals` and the bus option of `plan_journey`) |

The three tables fall back to the copies packaged in the wheel when no checkout is present (an installed
`ibb-mcp`, the container image).

Over streamable HTTP the server is stateless (it issues no `Mcp-Session-Id`) and serves `GET /healthz`,
which answers from process state and local files only. These settings apply to that transport:

| Variable | Default | Effect |
|---|---|---|
| `NABIZ_API_KEYS` | empty (open) | comma-separated keys accepted in `X-API-Key`; a wrong or missing key gets one 401 message |
| `NABIZ_MCP_RATE_BURST` | `30` | token-bucket size per caller; each tool call costs its price in `TOOL_COSTS` (`src/ibb_mcp/server.py`) |
| `NABIZ_MCP_RATE_PER_MINUTE` | `12` | tokens refilled per minute per caller |
| `NABIZ_MCP_MAX_CLIENTS` | `1024` | callers remembered at once, as salted pseudonyms held in memory only |
| `NABIZ_MCP_CORS_ORIGINS` | empty (closed) | comma-separated origins allowed to call from a browser |
| `NABIZ_MCP_TRUSTED_PROXY_HOPS` | `0` | proxies whose `X-Forwarded-For` entry is trusted; set `1` behind the Container Apps ingress |
| `NABIZ_TRACE_CONSOLE` | unset | `1` prints spans to stderr (needs `opentelemetry-sdk`) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | unset | exports spans to Application Insights when the `telemetry` extra is installed; spans carry tool names and outcomes, never arguments |

### Calling the tools without an MCP client

The façade is ordinary async Python, which is also how the contract tests drive it:

```python
import asyncio
from ibb_mcp.tools import Nabiz

async def main() -> None:
    nabiz = Nabiz()
    try:
        arrivals = await nabiz.iett_next_arrivals(line_code="500T", stop="4.LEVENT METRO")
        for arrival in arrivals.data["arrivals"]:
            print(arrival["eta_minutes"], "min ·", arrival["method"], "·", arrival["confidence"])
        print("as of", arrivals.provenance.observed_at, "| cached:", arrivals.provenance.cached)
    finally:
        await nabiz.aclose()

asyncio.run(main())
```

---

## Please be polite — the budget is shared

These endpoints are public, unauthenticated and **not** rate-limited per user. That is exactly why they
are easy to break for everyone:

- the İETT position service documents a hard limit of **100 requests per hour** — for all of us together;
- `api.ibb.gov.tr` fronts *every* İBB service and starts returning HTTP 503 to all of them after roughly
  fifteen rapid requests.

The server already defends this on your behalf: a minimum 6-second interval per host, a self-imposed
budget of 80 İETT requests per hour, exponential backoff with jitter, and a single-flight TTL cache so
concurrent questions collapse into one upstream call (`src/ibb_mcp/http.py`, `src/ibb_mcp/cache.py`). What
that asks of you:

1. **Run one server per machine or per deployment**, not one per agent. Each process keeps its own cache
   and its own budget, so five copies mean five times the upstream traffic.
2. **Do not loop tools in a polling agent.** If you need a refresh cadence, take it from the cache TTLs in
   the table above; asking more often returns the same cached value while doing nothing useful.
3. **Use `NABIZ_OFFLINE=1` for development, tests and demos.** Recorded fixtures behave like the real
   thing for everything except freshness.
4. **Call `city_freshness` instead of guessing** whether data is stale, and pass the age through to your
   own users: `data_age_seconds`, how old the data is, not `age_seconds`, how long ago it was read.
5. **Keep the attribution** — İBB Open Data Portal, CC BY 4.0 — wherever the data surfaces.
6. A deployed HTTP server already limits each caller by tool price (`NABIZ_MCP_RATE_BURST`,
   `NABIZ_MCP_RATE_PER_MINUTE`) and can require `X-API-Key` (`NABIZ_API_KEYS`). A `rate_limited` answer
   carries `retry_after_seconds`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Client shows the server as failed to start | Absolute interpreter path missing. Desktop clients do not inherit your shell `PATH`; use `<repo>/.venv/bin/python`. |
| `iett_stops_search` answers `reference_data_missing` | GTFS not downloaded. `stops.csv` and `routes.csv` are not committed — fetch them into `NABIZ_GTFS_DIR` (`ibb_mcp.gtfs.download_gtfs`, resource URLs in `tests/fixtures/gtfs_resources.json`). `plan_journey` still answers without them, with the bus option withdrawn. |
| Answers say data is several minutes old | Working as designed. TTLs are per source and every result states its age; `city_freshness` shows all of them at once. |
| `RateLimitExceeded` on İETT tools | Our own 80/hour budget was hit before İBB's 100. Cached values are still served — wait for the window to slide instead of restarting the process, which only resets the counter, not İBB's. |
| `UpstreamUnavailable: … upstream Oracle hatası: ORA-…` | An İETT database error leaked through the SOAP response. It is upstream and usually transient; the cache keeps serving the last good read. |
| Traffic tool fails to parse a response | That endpoint returns XML unless `Accept: application/json` is sent. The client always sends it — if you see this, check for a proxy stripping headers. |
| Everything 503s at once | The shared gateway is throttling. Back off for a couple of minutes; the server retries with jittered exponential backoff and serves stale data meanwhile. |

---

Questions, or something behaving differently against live data?
[Open an issue](https://github.com/muratcan-ates/istanbul-nabiz/issues).
