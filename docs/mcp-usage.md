# Using `ibb-mcp` from your own agent

`ibb-mcp` is a plain [Model Context Protocol](https://modelcontextprotocol.io) server over İstanbul's live
open data: parking occupancy, bus positions and arrivals, metro disruptions and station accessibility, the
city traffic index, and air quality. Point any MCP client at it and those become tools your agent can call.

Every result carries a **provenance stamp** — source URL, observation time, and whether the read came from
a stale cache — so an agent using this server can cite what it says and state how old the data is.

> **Not an official İBB service.** Independent student project; see [../NOTICE.md](../NOTICE.md).
> Data: İBB Open Data Portal, İBB Open Data Licence (CC BY 4.0). If you ship something built on this,
> carry that attribution through to your users.

---

## Status

| | |
|---|---|
| Tool implementations (all 12) | **working** — `src/ibb_mcp/tools.py` |
| MCP server entry point (`src/ibb_mcp/server.py`) over **stdio** | **working** — `initialize`, `tools/list` (12) and `tools/call` verified against a real MCP client |
| The same entry point over **streamable HTTP** (`--transport http`) | **implemented, not yet exercised** — no client has driven it end to end |
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

The data is public and the key is optional; it exists so the deployment can rate-limit abusive callers and
protect the shared upstream budget, not to gate access.

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

All twelve tools are implemented in `src/ibb_mcp/tools.py` and exposed under these names (PLAN.md §5).
Parameters marked with a default are optional. Every tool returns a `ToolResult`:
`{ data, provenance: { source, source_url, observed_at, reported_at, cached, license }, note }`.

| Tool | Parameters | Returns | Upstream · cache TTL |
|---|---|---|---|
| `places_resolve` | `query` *(str)*, `limit=5` | matching places with `lat`, `lon`, `kind`, `district` | local gazetteer (276 entries) · static |
| `ispark_find_parking` | `place` *(str)* **or** `lat`+`lon`, `radius_km=1.5`, `min_free=1`, `open_now=true` (plus `with_tariff=true` on the Python façade only) | up to 5 car parks: name, free spaces / capacity, type (covered / open / on-street), tariff text as published, distance, `updateDate` | İSPARK `Park` + `ParkDetay` · 5 min |
| `ispark_typical_occupancy` | `park_id` *(int)*, `weekday=today` *(0 = Monday)*, `hour=now` | median occupancy %, p25/p75, sample count — or `available: false` with an explanation while history is still thin | collected history (`ispark_profile`) |
| `iett_stops_search` | `query` *(str)*, `limit=8` | stops: `stop_code`, `stop_id`, name, `lat`, `lon` | GTFS (15 390 rows in the export, 15 386 placeable) · static |
| `iett_line_buses` | `line_code` *(str, e.g. `"500T"`)*, `direction=None` | vehicles on the line: door number, direction, nearest stop, last position time; plus the directions currently running | `GetHatOtoKonum_json` · 60 s |
| `iett_next_arrivals` | `line_code` *(str)*, `stop` *(stop code or stop name)*, `limit=3` | estimated arrivals: minutes, stops away, `method` (`stop_sequence` / `distance` / `schedule`), confidence, plus `diagnostics` and an explicit estimate disclaimer | live positions + GTFS order + timetable |
| `metro_status` | `line=None` *(e.g. `"M4"`)* | live disruption notices per line; an empty result means "no disruption reported", stated as such | `GetServiceStatuses` · 5 min |
| `metro_station_info` | `name` *(str)* | line, order on the line, coordinates, and accessibility: lift, escalator count, baby room, WC, prayer room | `GetStations` · 1 day |
| `traffic_index` | `window="now"` \| `"24h"` | `now`: index 1–99 with a plain-language description. `24h`: hourly history plus a comparison with the same hour yesterday | traffic index · 5 min |
| `air_quality_now` | `place` *(str)* | nearest of the 28 stations, latest hourly PM10 / SO2 / O3 / NO2 / CO, published AQI with its band, health disclaimer | `GetAQIByStationId` · 30 min |
| `air_quality_forecast` | `place` *(str)*, `horizon_hours=6` *(keep it ≤ 6; larger values are accepted but not meaningful — the baseline just repeats yesterday)* | hourly PM10 outlook, the cleanest upcoming window, and a flag saying the current method is a seasonal-naive baseline | 48 h of history + baseline model |
| `city_freshness` | — | per source: age of the last successful read, health, hit/miss/stale counters; remaining request budget; attribution text | in-process cache |

Two parameters read differently from the sketch in PLAN.md §5, and the wider form was kept because it is
what people actually type:

- `iett_next_arrivals(stop=…)` accepts a **stop code or a stop name**, not only the `stop_id` of the
  original sketch — a numeric argument is looked up as a code, anything else is searched by name.
- `air_quality_now(place=…)` and `air_quality_forecast(place=…)` take a **place name** (district,
  neighbourhood, landmark or station) and resolve it to the nearest of the 28 stations, rather than
  requiring a station GUID.

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

### Calling the tools without an MCP client

The façade is ordinary async Python, which is also how the contract tests drive it:

```python
import asyncio
from ibb_mcp.tools import Nabiz

async def main() -> None:
    nabiz = Nabiz()
    try:
        arrivals = await nabiz.iett_next_arrivals(line_code="500T", stop="Kadıköy")
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
   own users.
5. **Keep the attribution** — İBB Open Data Portal, CC BY 4.0 — wherever the data surfaces.
6. If you deploy this publicly, put your own rate limit in front of it. The `X-API-Key` header exists for
   that.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Client shows the server as failed to start | Absolute interpreter path missing. Desktop clients do not inherit your shell `PATH`; use `<repo>/.venv/bin/python`. |
| `iett_stops_search` returns nothing | GTFS not downloaded. `stops.csv` and `routes.csv` are not committed — fetch them into `NABIZ_GTFS_DIR` (`ibb_mcp.gtfs.download_gtfs`, resource URLs in `tests/fixtures/gtfs_resources.json`). |
| Answers say data is several minutes old | Working as designed. TTLs are per source and every result states its age; `city_freshness` shows all of them at once. |
| `RateLimitExceeded` on İETT tools | Our own 80/hour budget was hit before İBB's 100. Cached values are still served — wait for the window to slide instead of restarting the process, which only resets the counter, not İBB's. |
| `UpstreamUnavailable: … upstream Oracle hatası: ORA-…` | An İETT database error leaked through the SOAP response. It is upstream and usually transient; the cache keeps serving the last good read. |
| Traffic tool fails to parse a response | That endpoint returns XML unless `Accept: application/json` is sent. The client always sends it — if you see this, check for a proxy stripping headers. |
| Everything 503s at once | The shared gateway is throttling. Back off for a couple of minutes; the server retries with jittered exponential backoff and serves stale data meanwhile. |

---

Questions, or something behaving differently against live data?
[Open an issue](https://github.com/muratcan-ates/istanbul-nabiz/issues).
