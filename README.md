# İstanbul Nabız

**An unofficial city assistant for İstanbul, built on İBB's open data**: ask in plain Turkish or English,
get a short answer with its source and time, and hand a problem to the right office. Underneath it is an
MCP server (`ibb-mcp`, 18 tools) that any agent, VS Code Copilot included, can call.

[![CI](https://github.com/muratcan-ates/istanbul-nabiz/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/muratcan-ates/istanbul-nabiz/actions/workflows/ci.yml)
[![licence](https://img.shields.io/badge/code-MIT-blue)](LICENSE)
[![data](https://img.shields.io/badge/data-%C4%B0BB%20Open%20Data%20%C2%B7%20CC%20BY%204.0-blue)](https://data.ibb.gov.tr/license)
[![python](https://img.shields.io/badge/python-3.12-blue)](pyproject.toml)

> **This is not an official İBB service.** İstanbul Nabız is an independent student project. It is not
> affiliated with, endorsed by or operated by the İstanbul Metropolitan Municipality (İBB), İETT, İSPARK
> or Metro İstanbul. Organisation names appear only to attribute the source of the data.
>
> Contains public sector information from the İstanbul Metropolitan Municipality Open Data Portal,
> licensed under the İBB Open Data Licence (CC BY 4.0): <https://data.ibb.gov.tr/license>.
> Full attribution, personal-data handling and rate-limit policy: **[NOTICE.md](NOTICE.md)**.

**Herkes için, her zaman, her yerde.** Accessibility is the product, not a feature: step-free routes, an
easy-read screen, answers read aloud, and a 112 card that opens in the visitors' languages, with or without a model.

---

## What it does

İBB publishes many open datasets, 41 of them as APIs ([enumerated 13 Sep](docs/events_research.md)), behind
separate SOAP and REST endpoints and separate apps. Nabız puts one conversation in front of them, keeps the
history İBB does not, and never invents a number.

**Three stories the demo walks through:**

| # | A citizen says | What Nabız does |
|---|---|---|
| 1 | *"How do I get from Kadıköy to Levent without stairs?"* (typed or spoken) | resolves the places and checks the lifts and escalators Metro İstanbul records as out of service; step-by-step directions need the model or the walking-route key, and without them the answer says what it could check. Answers are read aloud on request |
| 2 | *"What's on this weekend that suits me?"* | remembers only what the person chose to keep (in the browser), suggests events from Kültür AŞ's calendar, and puts a plan on the **Takvim** tab's week grid or into a calendar file |
| 3 | A photo of a broken ramp | strips the photo's metadata, masks health details and identity numbers, routes it to a simulated operator desk, and gives the citizen one tracking code to see the outcome; "resolved" only when the citizen confirms |

**What a citizen sees** (`/`, the product app): a chat with three places, **Asistan**, **Takvim** and
**Hesabım**; history and memory kept in the browser (30 days from last use; "forget" means forget); a
week-and-hour calendar; English beside Turkish; *Kolay ekran* (easy read), text-to-speech and voice input;
an official-path card that says which office owns a problem (İSKİ, İGDAŞ, Metro İstanbul, the district)
and never files anything on the person's behalf. More views sit behind "Daha fazla": city status, journeys,
the map, what is near me, tourist mode, İstanbulkart and bill helpers, a household outage watch, a disaster
preparedness file and more (DECISIONS #79 to #97).

**What an operator sees** (`/console`, simulated): a decision desk that starts with today's counts, then
notifications, citizen requests, system status and planning. Behind it runs **NEXUS**, a small decision
core: signals, rules, an evidence "Arena" with three seats, human approval and a hash-chained ledger.

**Three things make this more than a chatbot:**

1. **It protects the upstream.** The İETT service documents a hard limit of 100 requests/hour and the İBB
   gateway starts 503-ing *every* service after roughly fifteen rapid calls. One shared rate-limited client
   plus a TTL cache with single-flight means N concurrent users produce at most one upstream request
   (`src/ibb_mcp/http.py`, `src/ibb_mcp/cache.py`); over HTTP each caller also has its own budget, priced by
   how far upstream a tool can reach (DECISIONS #15).
2. **It keeps the history İBB does not.** İBB publishes current state only. A collector archives parking
   occupancy, vehicle positions and its own arrival predictions, which is what makes "usually at this
   hour", line regularity and a *measured* ETA error possible at all.
3. **It never invents a number.** Every tool returns a `ToolResult` carrying provenance (source URL,
   observation time, whether the read was stale). Recorded data is labelled as recorded, never as live; an
   input that could not be read is reported as unknown rather than as good news; the agent's faithfulness
   check rejects any number in an answer that is not in a tool result, and hotline numbers are checked
   against the official list.

**Safety and privacy by construction:** a 112 card that opens from rules alone, even with the model off or
the chat paused; health statements masked before the queue, the log and the model (DECISIONS #65 and the
P09a-2 notes); no user location server-side; account erasure as one chain over every store (DECISIONS
#104); a red-team set in `eval/red_team.jsonl` and `eval/red_team_extra.jsonl` run in every test pass.

The MCP tools behind it, one journey each in `eval/journeys.jsonl`:

| # | Who | The question | Tool chain |
|---|---|---|---|
| **J1** | Driver | *"I'm reaching Taksim in 20 minutes. Which car park will have space, and what does it cost?"* | `places_resolve` → `ispark_find_parking` → `ispark_typical_occupancy` |
| **J2** | Bus passenger | *"When does the 500T reach 4. Levent?"* | `iett_stops_search` → `iett_next_arrivals` |
| **J3** | Metro passenger | *"Any disruption on M4? Is there a lift at Kartal?"* | `metro_status` → `metro_station_info` |
| **J4** | Runner, parent | *"When is the air good enough for a run in Beşiktaş today?"* | `air_quality_now` → `air_quality_forecast` |
| **J5** | Commuter | *"Taksim to Kadıköy right now: car or metro?"* | `plan_journey`, `line_reliability`, `check_alerts`, `traffic_index` |
| **J6** | Step-free traveller | *"Which lifts are out on M2?"* | `metro_equipment_status` |

## Project status (28 September 2026, `main` at `c568f84`)

Everything below runs on a laptop; nothing is deployed yet. The day-by-day plan is
[docs/SPRINT.md](docs/SPRINT.md) and every design choice is in [DECISIONS.md](DECISIONS.md) (110 entries).

| Layer | State | Where |
|---|---|---|
| Citizen app: chat shell, answer cards, history and memory, calendar, accessibility, English | **working locally** (`make console`, `/`) | `src/nabiz/console/static/`, DECISIONS #106 to #108 |
| Operator console and NEXUS decision core | **working locally**, simulated operator (`/console`) | `src/nabiz/console/`, `src/nexus_core/` |
| 18 MCP tools behind one façade, plus `ibb://attribution` | **working**: offline tests and a real MCP client over stdio (`tests/test_mcp_integration.py`) | `src/ibb_mcp/tools.py`, `src/ibb_mcp/server.py` |
| İBB client, cache, GTFS repair, ETA engine | **working**; arrivals use the untuned 120 s/stop, the estimator with the better held-out score (DECISIONS #18) | `src/ibb_mcp/` |
| City agent | **working without a model** (rules and templates, clearly labelled); the model path (Azure OpenAI or any `/chat/completions`) is wired and has **not yet been measured on a real model** | `src/nabiz/agent/`, `scripts/model_acceptance.py` |
| Keyed services: Azure Maps walking route, Azure Speech, Microsoft sign-in and Outlook | **mounted, off** until their keys are set; the page says "not connected" instead of pretending (DECISIONS #98, #100, #109) | `src/nabiz/console/` |
| Collector | the owner's laptop today; five scheduled Container Apps Jobs written and tested offline, not deployed | `scripts/collect_forever.py`, `infra/modules/collectorjobs.bicep` |
| Infrastructure | **written, never deployed**: Bicep + `azd`, one `Dockerfile` | `infra/`, `azure.yaml`, [docs/deploy.md](docs/deploy.md) |
| Tests and eval | see *Sayılar* below; every number is in `eval/results/numbers.md` | `tests/`, `eval/` |

## Sayılar

Sunumda söylenen her sayı bu tablodan okunur; her satır ölçüm dosyasını ve komutunu adlandırır. Burada olmayan
bir sayı sunumda söylenmez.

| Ne | Değer | Kaynak · komut · tarih |
|---|---|---|
| Otobüs varış tahmininin ortalama mutlak hatası (ölçüldü; henüz iyi değil) | **12,94 dk** (n = 1.351) | `eval/results/eta.md` · `make eta` · 8–22 Eyl verisi |
| Modelsiz ajan cevaplarında kaynağıyla eşleşen sayı (şablon cevap, model yok) | **126/126** | `eval/results/20260908T082619Z-agent-offline.md` · 8 Eyl |
| MCP aracı | **18** | `eval/results/numbers.md` · `scripts/demo_numbers.py --write` · 28 Eyl |
| Test | **5.255 geçti** (5.285 toplandı) | same |
| Eval senaryosu | **66/66** geçti (78 senaryo; 12 tanesi yalnız ajan modunda, atlandı) | same |
| Bilgi soru seti | 100 soru, şema doğrulandı; isabet ölçülmedi | same |

Yeni satır aynı kurala uyar; sitede test ve eval sayıları `/nasil.html` sayfasında `eval/results/numbers.md`'den
okunur.

## Architecture

![İstanbul Nabız architecture](docs/architecture.svg)

Read it left to right: six İBB endpoints, one rate-limited client they all pass through, a collector that
keeps the history İBB does not, and one tool layer that the MCP server, the web page and the agent all
call. The Azure half is the **target**, written in `infra/` but not deployed; today the collector runs on the
owner's laptop (the dashed box). The mermaid source below says the same thing for readers who prefer text.

```mermaid
flowchart LR
  subgraph IBB["İBB live services (api.ibb.gov.tr, no registration)"]
    P[İSPARK Park / ParkDetay<br/>~10 min]
    B[İETT SOAP<br/>line and fleet positions · timetable<br/>100 req/hour]
    G[(İETT GTFS<br/>stops · routes · stop_times · Mar 2026)]
    M[Metro İstanbul REST<br/>service status · stations]
    T[Traffic index<br/>5 min · 28-day hourly history]
    AQ[Air quality<br/>28 stations · hourly]
  end
  subgraph NOW["Today: the owner's laptop"]
    LC[collect_forever.py<br/>under a supervisor]
    LL[(data/lake<br/>gzipped NDJSON)]
  end
  subgraph AZ["Azure target (Bicep + azd, not deployed)"]
    J[Container Apps Jobs x5<br/>scheduled collector]
    BL[(Blob Storage<br/>bronze NDJSON)]
    K[(Azure Data Explorer free<br/>optional)]
    MCP[Container Apps<br/>ibb-mcp · stateless HTTP · /healthz]
    AI[Application Insights<br/>allow-listed spans]
  end
  REF[(data/reference<br/>occupancy · reliability · ETA rates)]
  TL[Tool layer · Nabiz<br/>18 tools · shared cache · PoliteClient]
  subgraph CL["Clients"]
    WEB[Nabız web page]
    AG[Nabız agent<br/>tool loop + faithfulness check]
    VS[VS Code Copilot · Claude · any MCP client]
  end
  subgraph LLM["LLM (optional, env switch)"]
    AO[Azure OpenAI or any /chat/completions]
    FL[Foundry Local · on-device]
  end
  P & B & M & T & AQ --> LC --> LL
  P & B & M & T & AQ -. target .-> J --> BL -.-> K
  LL -->|build_profiles · reliability_report · calibrate_eta| REF
  P & B & M & T & AQ --> TL
  G --> TL
  REF --> TL
  TL --> MCP --> VS
  TL --> WEB
  TL --> AG
  AG --> AO
  AG -.-> FL
  MCP & J --> AI
```

The MCP server is the product; the page and the agent are its first customers. All three read the same
cached, provenance-stamped tool layer, so a question asked in VS Code Copilot and the same question asked on
the Nabız page hit identical code and identical numbers. See [DECISIONS.md](DECISIONS.md) for why each box
is what it is: #10 for the collector's move to Container Apps Jobs, #14 for the rail graph behind the mode
comparison.

## Results

Every number below is copied from a file in `eval/results/` or `data/reference/`, and the file is named in
the row. A fit scored on the data it was fitted on is labelled **in-sample** and is never presented as
accuracy. Where a metric cannot be computed it says so and why.

| Metric | Result | Source · how it is measured |
|---|---|---|
| Task success rate (data layer) | **24/24** offline · **13/13** live | `eval/results/20260908T084817Z-deterministic-offline.md` · `eval/results/20260908T084908Z-deterministic-live.md` (= `latest.md`), 8 Sep, J1–J4. A scenario passes when every call returns or refuses where it should and every required field is present. The live run stopped at its own 8-request ceiling after 13 scenarios; the J5 scenarios added on 23 Sep are in no committed run yet |
| Tool success rate | 34/34 offline · 19/19 live | same two files |
| Number-plate leaks | **0** | same two files; also asserted by the tests and by `scripts/guardrails.py` |
| Bus ETA mean absolute error | **12.94 min** (n = 1,351 of 6,801 predictions, 8–22 Sep), *not shippable, see below* | `eval/results/eta.md` (`make eta`): every logged prediction paired with the vehicle later observed at that stop. All of them used the untuned 120 s/stop |
| within 5 minutes | 27.3% | same |
| by method | `stop_sequence` 12.74 min (n = 1,240) · `distance` 15.16 min (n = 111) | same |
| Calibrated ETA rates, held out | **35.82 min** against 10.18 min for the untuned rate, on the same 523 predictions made after the fit | `eval/results/eta.md`, "Held-out replay" (`make eta-holdout`): the calibration makes the estimate worse on stops it never saw |
| Calibrated ETA rates, in-sample | 11.16 min for the per-bucket rates (served only in the calibrated mode, see below), 12.37 min for the single 235 s/stop rate, both on the 500 predictions they were fitted on: fits, not accuracy | `eval/results/eta.md` ("What 12.37 and 11.2 are") · `data/reference/eta_profile.json` (`overall.mae_minutes`) |
| Line regularity | 15 of 39 line-hour cells published, 24 refused for too few observations; 2 calendar days (8 and 13 Sep) | `eval/results/reliability.md`, `data/reference/line_reliability.json` |
| "Usually at this hour" parking | 0 of 3,216 cells pass the profile's own guards (16,325 snapshot rows, 8–13 Sep), so the tool answers "not enough history yet" | `data/reference/occupancy_profile.json` |
| Agent without a model | 9/24 scenarios; tool-call accuracy 41.7% exact chain; numeric faithfulness 126/126 numbers in its templated answers | `eval/results/20260908T082619Z-agent-offline.md`: keyword routing and templates, not a model |
| Agent with a model | n/a (never evaluated on a real model) | needs an LLM endpoint (DECISIONS #5) |
| p95 end-to-end latency | 27 ms offline · 17,819 ms live, cold | `eval/results/20260908T084817Z-deterministic-offline.md` · `eval/results/20260908T084908Z-deterministic-live.md`; live includes our own ≥ 6 s spacing before each upstream call: politeness, not İBB being slow |
| Data freshness at answer time | 48 s median, live | `eval/results/20260908T084908Z-deterministic-live.md`, age of the reading itself (`provenance.reported_at`) |

**About that ETA number.** 12.94 minutes is bad and it is published anyway, because the harness exists to
catch exactly this. It measures the untuned 120 s/stop estimator: the collector logs every prediction at
that rate. The per-bucket rates calibrated on 13 September scored 11.16 minutes
only on the 500 predictions they were fitted on (two 500T stops; the single 235 s/stop rate scored 12.37
there); replayed on 523 later predictions at stops the fit never saw, they scored 35.82 minutes against
10.18 for the untuned rate. Seconds per stop belongs to a stretch of road, not
to a line, so the next model has to account for stop spacing. Since 2026-09-23 `iett_next_arrivals` and the
bus leg of `plan_journey` serve the untuned 120 s/stop, the estimator with the better held-out score, and the
calibrated rates only with `NABIZ_ETA_PROFILE_MODE=calibrated` (DECISIONS #18). Every arrival says which rate
it used and why (`diagnostics.rate_mode`, `rate_reason`).
Method, the before/after split, limits and history: `eval/results/eta.md`.

## Verified data facts

Every row here was confirmed by a real call on **7–8 September 2026**; the recorded responses (trimmed
samples) are committed in `tests/fixtures/` alongside `_capture_report.json` (URL, status, byte count,
latency per call). This section exists because the interesting engineering in a public-data project is
rarely the happy path.

| Source | Endpoint | Returns | Refresh | Trap, and where it is handled |
|---|---|---|---|---|
| İSPARK lots | `GET /ispark/Park` | 249 car parks: `parkID, parkName, lat, lng, capacity, emptyCapacity, workHours, parkType, freeTime, district, isOpen` | ~10 min | `lat`/`lng` arrive as **strings**; one call covers the whole city, so "parking near me" is a filter over a shared cached fetch, never a per-user request · `sources/ispark.py` |
| İSPARK detail | `GET /ispark/ParkDetay?id=<parkID>` | adds `updateDate`, `monthlyFee`, `tariff` (free text), `address`, `areaPolygon` (WKT) | ~10 min | **An unknown id returns a plausible dummy record** (capacity 1) instead of an error, so ids are validated against the live list before the call. The tariff text is shown verbatim, never parsed · `sources/ispark.py` |
| İETT line positions | `POST .../SeferGerceklesme.asmx`, action `GetHatOtoKonum_json` | vehicles on one line (31 for 500T at capture): `kapino, boylam, enlem, guzergahkodu, hatad, yon, son_konum_zamani, yakinDurakKodu` | seconds | The JSON is an **XML-entity-escaped string inside `<…Result>`**, and Oracle `ORA-` errors leak through as plain text in the same element · `http.extract_soap_json` |
| İETT fleet | same service, `GetFiloAracKonum_json` | 6 911 vehicles, 1.1 MB: `Operator, Garaj, KapiNo, Saat, Boylam, Enlem, Hiz, Plaka` | seconds | **Documented limit: 100 requests/hour.** Our own budget stops at 80/hour before İBB does. `Plaka` (number plate) is dropped at the parsing boundary and never stored or returned; the recorded fixtures carry synthetic plates (`00 XX 001` …) · `http.HourlyBudget`, `models.BusPosition.from_fleet_raw`, [NOTICE.md](NOTICE.md) |
| İETT timetable | `.../PlanlananSeferSaati.asmx`, `GetPlanlananSeferSaati_json` | 702 planned departures for 500T: `SHATKODU, SGUZERAH, SYON, SGUNTIPI (I/C/P), DT` | daily | Day type is a single letter (`I` weekday, `C` Saturday, `P` Sunday), and it is a **departure** from the terminus, not an arrival at your stop; the ETA engine labels it as such · `models.day_type_for`, `eta.py` |
| İETT GTFS | `data.ibb.gov.tr` dataset `iett-gtfs-verisi` | 15 390 stops, 9 279 routes (Mar 2026) | ~6 months | Separator is **`;`**, file has a **UTF-8 BOM**, coordinates carry thousands separators (`410.191.700.005.564` = `41.0191700005564`, 4 stops still land outside İstanbul and are dropped), and `routes.csv` text is **double-encoded mojibake** (`KADIKÃ–Y` = `KADIKÖY`) · `models.repair_coordinate`, `models.demojibake`, `gtfs.py` |
| **The join** | live → static | `yakinDurakKodu` → `stops.**stop_code**` (31/31 matched on 500T); `guzergahkodu` → `routes.route_code` (2/2) | n/a | It is `stop_code`, **not** `stop_id`: different number spaces in this export. Joining on `stop_id` matches nothing and the ETA tool would quietly answer "no buses" · `gtfs.py` |
| Metro status | `GET .../V2/GetServiceStatuses` | `{Success, Error, Data:[{LineId, LineName, Description, IsActive, UpdateDate, …}]}` | live | Only lines **with a notice** are listed. An empty `Data` means "no disruption reported", not "no data", and `Success: false` is a real failure, not an empty result · `sources/metro.py` |
| Metro stations | `GET .../V2/GetStations` | 248 stations with `DetailInfo:{Escolator, Lift, BabyRoom, WC, Masjid, Latitude, Longitude}` | static | The escalator field is misspelled **`Escolator`**; `Name` is shouted and de-diacriticised (`YENIKAPI`) while `Description` holds the human form (`Yenikapı`): display uses `Description` · `sources/metro.py` |
| Traffic index | `GET /tkmservices/api/TrafficData/v1/TrafficIndexHistory/{days}/{5M\|H\|D\|M\|Y}` | `[{TrafficIndex: 1–99, TrafficIndexDate}]`; `/1/H` returns 25 points | 5 min | **Returns XML unless `Accept: application/json` is sent**: without the header JSON parsing fails with a confusing error. The 25-point shape gives "now vs. same hour yesterday" from a single call. A missing index is kept as missing, never read as 0 ("akıcı") · `sources/traffic.py`, `models.TrafficIndexPoint` |
| Air quality | `GetAQIStations` (28) · `GetAQIByStationId?StationId=<guid>&StartDate=dd.MM.yyyy HH:mm:ss&EndDate=…` | hourly `Concentration{PM10, SO2, O3, NO2, CO}` + `AQI{AQIIndex, ContaminantParameter, State, Color}`, back to at least 2023 | hourly | **`AQIIndex` is a rolling 24-hour mean for PM10**, so it lags the air you would breathe on a run; for short-horizon questions the hourly *concentration* is the honest signal. `EndDate` is inclusive (dedupe on `ReadTime`); a 30-day window returned all 744 rows; **PM2.5 is not in this API**; NO2/CO are frequently null · `sources/airquality.py` |

Re-capture the fixtures with `make fixtures` (**NETWORK**, owner only). It spaces gateway calls ≥ 7 s apart,
makes at most three İETT SOAP calls and swaps every plate for a synthetic one before writing. **Run it
sparingly**: the budget it protects is shared with everyone else using these public endpoints.

## Quickstart

```bash
git clone https://github.com/muratcan-ates/istanbul-nabiz.git
cd istanbul-nabiz

make venv          # uv venv -p 3.12 .venv (the system 3.14 is not supported by every dependency yet)
make install       # editable install with the dev and web extras (EXTRAS=dev,web,collector for more)

make test          # the suite, offline: tests/conftest.py fails any test that tries the network
make lint smoke guardrails   # the other gates CI runs, with:
make architecture web-budget # import layers and size ratchets; the page's byte, font and token budget
make ci-local      # every CI gate on a clean copy of exactly what a push would publish
```

**Reference data.** Committed: `data/reference/places.csv` (276 places: metro stations, air-quality
stations, district centroids, landmarks; `make places` rebuilds it), the three derived tables
(`occupancy_profile.json`, `line_reliability.json`, `eta_profile.json`, rebuilt from the local lake by
`scripts/build_profiles.py`, `scripts/reliability_report.py` and `scripts/calibrate_eta.py`), and a 38 KB
cut of the GTFS export in `tests/fixtures/gtfs_mini/` that the tests read. The full GTFS export is *not*
committed; download it into `data/reference/gtfs/` with `ibb_mcp.gtfs.download_gtfs` (resource URLs in
`tests/fixtures/gtfs_resources.json`) and build its stop-sequence cache with `make sequences`. Without it
the two stop tools answer `reference_data_missing` and `plan_journey` withdraws its bus option.

**Offline mode.** `NABIZ_OFFLINE=1` makes every source read from `tests/fixtures/` instead of the network,
which is how the demo stays reproducible on a bad conference wifi. Every other setting is listed in
[docs/mcp-usage.md](docs/mcp-usage.md#configuration).

**Check the environment.** `scripts/probe_day0.py` is the pre-flight gate: 21 numbered checks over the
local toolchain, the Azure subscription's regional constraints, the six İBB endpoints and the live-bus →
GTFS join, printed as a PASS/FAIL/SKIP table and written to `docs/day0_report.json` (home paths shortened
to `~`; no subscription or tenant id is recorded).

```bash
./.venv/bin/python scripts/probe_day0.py --no-network  # local checks only, safe to re-run
./.venv/bin/python scripts/probe_day0.py               # NETWORK: + İBB and GTFS (6 gateway calls, spaced)
./.venv/bin/python scripts/probe_day0.py --azure       # NETWORK: + the az subscription checks
```

**Run the MCP server.** `ibb-mcp` is the console script declared in `pyproject.toml`; it registers the 18
tools below and an `ibb://attribution` resource.

```bash
make mcp                                  # stdio, the shape VS Code and Claude launch
.venv/bin/ibb-mcp --offline               # stdio, served from tests/fixtures (reproducible demo)
make mcp-http                             # streamable HTTP on 127.0.0.1:8000, the shape Container Apps runs
NABIZ_OFFLINE=1 make web                  # the web page on http://127.0.0.1:8080, from fixtures
make console                              # the product app on http://127.0.0.1:8090: citizen face at /, simulated operator at /console
NABIZ_OFFLINE=1 make console              # the same, from recordings only (no İBB call)
make console-offline                      # the same from recordings, without reading .env or probing a model (CONSOLE_PORT=8090)
```

The product app (`python -m nabiz.console`) reads `.env`, binds the decision core (`nexus_core`, ledger in
`data/nexus/nexus.db`, rules in `missions/*.toml`) and feeds it the Metro equipment snapshot and a small city
watch (car parks, air quality, one bus line) when the console's queue is read, at most every 300 s. Without a
model the Arena's three seats are rule-based and say so; with `NABIZ_LLM_*` set, each seat is one model call
over the card's evidence, on the Arena's own daily ceiling. `POST /api/console/simulate` replays a recorded
signal, never live data. The console answers only on this machine unless `NABIZ_CONSOLE_TOKEN` is set; then
`/console` asks for that key (DECISIONS #25).

| Tool | What it answers |
|---|---|
| `places_resolve(query, limit)` | a place name → coordinates, from the local gazetteer |
| `ispark_find_parking(place \| lat+lon, radius_km, min_free, open_now)` | car parks near a place with live free spaces and the tariff as published |
| `ispark_typical_occupancy(park_id, weekday, hour)` | measured occupancy history for one car park, or why there is not enough |
| `iett_stops_search(query, limit)` | bus stops by name, from GTFS |
| `iett_line_buses(line_code, direction)` | where a line's buses are now; with the GTFS export present, a code İETT does not list is refused before it costs an İETT request |
| `iett_next_arrivals(line_code, stop, limit)` | estimated arrivals, each with its method and confidence; a stop the line never calls at is refused, and so is a code İETT does not list (with the GTFS export present) |
| `metro_status(line)` | live disruption notices; no notice means none reported |
| `metro_station_info(name)` | a station's lift, escalators, baby room, WC and prayer room |
| `metro_equipment_status(station, line, group)` | lifts, escalators and moving walkways Metro İstanbul records as unusable, with İBB's type and recorded date (meaning undocumented), a station's lift state and uncertainty codes; never "working" |
| `traffic_index(window)` | the city traffic index now, against the same weekday and hour's median, or its last 24 hours |
| `air_quality_now(place)` | the nearest station's latest reading, AQI band and a health disclaimer |
| `air_quality_forecast(place, horizon_hours)` | a baseline PM10 outlook and the cleanest upcoming window |
| `city_freshness()` | how old each source's data is, and how much request budget is left |
| `plan_journey(origin, destination \| lat+lon pairs)` | drive, metro, one bus line and walking compared, with every assumption; not navigation |
| `line_reliability(line_code, hour)` | measured headway and bunching for a line and hour, over a stated window |
| `check_alerts(subscription)` | a client-held alert subscription evaluated once, stored nowhere |
| `ibb_datasets_search(query, category, limit)` | datasets in İBB's open data catalogue, from a recorded copy |
| `ibb_services_search(query, limit)` | quoted passages from İBB's own service pages, from the local knowledge index |

The same tools are callable directly from Python, which is how the contract tests drive them:

```python
import asyncio
from ibb_mcp.tools import Nabiz

async def main() -> None:
    nabiz = Nabiz()
    result = await nabiz.ispark_find_parking(place="Taksim", radius_km=1.0)
    print(result.data["count"], "car parks;", result.provenance.source_url)
    await nabiz.aclose()

asyncio.run(main())
```

## Use it from your own Copilot

`ibb-mcp` is a plain MCP server: point VS Code / GitHub Copilot agent mode, Claude Desktop, Claude Code or
any other MCP client at it and İBB's live data becomes available to *your* agent, with the same caching and
the same provenance.

**→ [docs/mcp-usage.md](docs/mcp-usage.md)**: copy-pasteable stdio and HTTP configuration, the full tool
reference with parameters and return shapes, the failure kinds, and a note on sharing the rate budget.

## The citizen page and its design

The product app's citizen page (`make console`, then `/`) is a chat first: the composer is the hero, one
primary action ("Sor"), and every answer card has the same anatomy: a short answer, one source line with
its date, and at most one row of actions (copy, listen, call 153, the official page). Its design language,
**Nabız Dili**, is written down in [docs/design/DESIGN.md](docs/design/DESIGN.md) and DECISIONS #58 to #63:

- **Tokens from Fluent 2**, an İznik-blue palette checked for WCAG AA in light and dark, one icon family.
- **Honest labels.** "Resmî İBB hizmeti değildir" at every width; recorded data says *kayıtlı* and its time,
  never *canlı*; a service that needs a key says it is not connected.
- **Motion that respects the reader.** Transform and opacity only, off under reduced motion; the gate in
  `scripts/check_web_budget.py` holds every stylesheet to it.
- **Measured weight.** The citizen page is in the web budget since 28 Sep (DECISIONS #110); today it is over
  its budget and recorded as a target that may only shrink, by lazy-loading the views hidden at load.

The older standalone page (`make web`, `src/nabiz/web/`) is the MCP server's first client and keeps its own
budget.

## How this repository is built

One person, several coding agents working in parallel lanes, and rules that keep the result honest:

- **[AGENTS.md](AGENTS.md)**: the binding rules for any agent: lanes and file ownership, no AI
  attribution, nothing personal in a public tree, never call İBB from tests, sourced numbers only.
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: setup, the checks, commit style and identity.
- **[docs/ENGINEERING.md](docs/ENGINEERING.md)**: the engineering rules, each tied to an incident or a
  reference, and a dated, unflattering self-assessment.
- **Gates on the code's shape and cost** (ENGINEERING §13 and §14), all three in CI: `make architecture`
  fences the import layers (`ibb_mcp` never imports `nabiz`) and ratchets module, class and function size
  against `scripts/architecture_baseline.json`, so measured debt cannot grow past its entry (raising an entry
  is a reviewed change); `tests/test_performance_budgets.py` counts upstream calls per tool at the cache and
  at the boundary (zero when the cache is warm), single flight, stale-on-error and parses per process; `make web-budget` holds the page to its byte, font, motion and colour-token budgets.
- **[docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)** and **[SECURITY.md](SECURITY.md)**: what is protected,
  by which file, and how to report a vulnerability privately.
- **[docs/privacy.md](docs/privacy.md)**: why no location is stored server-side, and the tests that hold it.
- **[docs/SPRINT.md](docs/SPRINT.md)** · **[PLAN.md](PLAN.md)** · **[DECISIONS.md](DECISIONS.md)**: the
  plan to delivery, the original plan with its dated status, and 110 decisions with their reasons.

## Limitations

Stated plainly, because a public-data project that hides these is not trustworthy:

- **Bus arrivals are estimates, not a timetable guarantee**, and today they are not accurate enough (see
  Results). They come from live vehicle positions, GTFS stop order and the published schedule; each
  estimate reports the method behind it. Plan journeys with official İETT and Metro İstanbul sources.
- **The mode comparison is an estimate, not navigation.** Rail runs over Metro İstanbul's station list with
  a flat 6-minute headway and one published check (M7: 38.9 min modelled against 36 published); the drive
  estimate has no ground truth. Every option says so ([docs/route-advisor.md](docs/route-advisor.md)).
- **The history is thin.** The derived tables were built on 13 September from a collector that ran on a
  laptop and kept stopping: no parking cell passes its own guards yet, and line regularity covers two days.
  The tools say so instead of extrapolating.
- **28 air-quality stations, not 38.** The open API exposes 28; İBB's own map shows more. Coverage is
  uneven, so the nearest station may be some distance from you.
- **No PM2.5.** This API publishes PM10, SO2, O3, NO2 and CO only. NO2 and CO are frequently null.
- **The published AQI is a rolling 24-hour mean** for PM10 (8 hours for O3 and CO). It is the official
  band, but it is not what the air is doing this hour; the hourly concentration is reported next to it.
- **Air-quality forecasting is a seasonal-naive baseline**, and the result says so.
- **İSBİKE is out.** The bike-share service is closed; there is nothing live to read.
- **The traffic *density* dataset stops in January 2025.** Only the live 1–99 traffic *index* is current.
- **Parking occupancy is not instantaneous**: İSPARK refreshes roughly every 10 minutes, and every answer
  carries the age of the reading.
- **Some upstreams need a key or are shut**: hal (market) prices require a key, road-works returns 404.
- **The offline eval still needs the GTFS export for its bus-stop scenarios.** The tests run on a committed
  GTFS cut, but `eval/run_eval.py --offline` reads `data/reference/gtfs/`; on a clean clone without it four
  J2 scenarios fail (26/30, measured on a clean copy on 23 Sep).
- **The free Azure Data Explorer cluster has no SLA**, and the Azure for Students credit behind the rest of
  the deployment is finite; nothing is deployed yet.

## Roadmap

| | |
|---|---|
| **Deploy** | the MCP server and the collector jobs on Azure Container Apps ([docs/deploy.md](docs/deploy.md), [docs/SPRINT.md](docs/SPRINT.md) D3) |
| **Measure the model path** | Azure OpenAI on the same acceptance set (`scripts/model_acceptance.py --real`), then open the model answers by default |
| **Turn on the keyed services** | Azure Maps walking routes, Azure Speech, Microsoft sign-in with Outlook, each already mounted behind its key |
| **Eight languages** | German, Russian, French, Spanish, Arabic and Persian catalogues are staged on `bulut/p14-sekiz-dil`, waiting for the post-D2a keys |
| **A lighter citizen page** | lazy-load the views hidden at load and merge stylesheets, until the page meets its budget |
| **A better ETA model** | one that accounts for stop spacing, measured held out before it is served |
| **Publish `ibb-mcp` to PyPI** | one `uvx ibb-mcp` away from any MCP client, once the release name is decided |
| **Specialised agents** | a transit agent, a parking agent and an environment agent behind a router, instead of one prompt holding fourteen tools |
| **Push notifications** | for the stateless alert check, which today runs only while the page is open |
| **Copilot Studio connector** | the same server as a first-class Microsoft 365 agent tool |
| **Microsoft Fabric** | Eventhouse mirror of the ADX tables and a OneLake shortcut over the lake |
| **Event Hubs ingestion** | in place of the scheduled collector for the second-resolution fleet feed |
| **Azure Maps Search** | as a fallback for place names the local gazetteer misses |
| **LightGBM occupancy model** | once two or more weeks of parking history exist, measured against the median profile |

---

## Türkçe

**İstanbul Nabız**, İBB'nin açık verisi üzerine kurulmuş, resmî olmayan bir şehir asistanıdır. Soruyu
Türkçe ya da İngilizce yazarsınız (ya da söylersiniz); kısa bir cevap, kaynağı ve saatiyle gelir. Bir sorun
varsa doğru kurumu gösterir, sizin yerinize başvuru yapmaz. Altında her ajanın (VS Code Copilot dahil)
çağırabileceği **18 araçlı bir MCP sunucusu** (`ibb-mcp`) vardır.

> **Bu resmî bir İBB hizmeti değildir.** Bağımsız bir öğrenci projesidir; İBB, İETT, İSPARK veya Metro
> İstanbul ile bağlantılı, onlar tarafından desteklenen ya da onaylanan bir çalışma değildir. Ayrıntı:
> [NOTICE.md](NOTICE.md).
>
> Kamu sektörü bilgilerini içerir: İBB Açık Veri Portalı, İBB Açık Veri Lisansı (CC BY 4.0).

**Herkes için, her zaman, her yerde.** Erişilebilirlik bir özellik değil, ürünün kendisi: merdivensiz
rota, *Kolay ekran*, sesli okuma ve sesle soru, model kapalıyken bile ziyaretçi dillerinde açılan 112 kartı.

**Gösterimdeki üç hikâye**

| # | Vatandaş | Nabız |
|---|---|---|
| 1 | *"Kadıköy'den Levent'e merdivensiz nasıl giderim?"* (yazarak ya da sesle) | yerleri çözer, Metro İstanbul'un kullanılamaz diye kaydettiği asansör ve yürüyen merdivenlere bakar; adım adım tarif için model ya da yürüyüş rotası anahtarı gerekir, yoksa neye bakabildiğini söyler. İsterse sesli okur |
| 2 | *"Bu hafta sonu bana uygun ne var?"* | yalnız kişinin saklamayı seçtiğini hatırlar (tarayıcıda), Kültür AŞ takviminden öneri yapar, planı **Takvim** sekmesindeki haftalık saat ızgarasına ya da takvim dosyasına koyar |
| 3 | Kırık rampanın fotoğrafı | fotoğrafın üst verisini siler, sağlık bilgisini ve kimlik numarasını gizler, örnek operatör masasına yönlendirir, vatandaşa tek bir takip kodu verir; "çözüldü" yalnız vatandaş onaylayınca |

**Vatandaş ekranı:** Asistan, Takvim, Hesabım; sohbet geçmişi ve hafıza tarayıcıda (son kullanımdan sonra 30
gün); İngilizce; Kolay ekran, sesli okuma ve sesle soru; hangi kurumun işi olduğunu söyleyen resmî yol kartı.
"Daha fazla" altında şehir durumu, yolculuk, harita, yakınımda, turist modu, İstanbulkart ve fatura
yardımcıları, hane kesinti takibi, afet hazırlık dosyası ve fazlası.
**Operatör ekranı** (`/console`, örnek): günün sayılarıyla açılan karar masası; arkasında sinyal, kural,
kanıt "Arena"sı, insan onayı ve zincirli defterden oluşan **NEXUS** karar çekirdeği.

**Neden bir sohbet botundan fazlası**

- **Servisleri korur.** İETT servisi saatte 100 istekle sınırlı; İBB ağ geçidi yaklaşık 15 hızlı çağrıdan
  sonra bütün servislere 503 döndürüyor. Tek istemci + tek uçuşlu TTL önbellek sayesinde eşzamanlı N
  kullanıcı en fazla bir yukarı akış isteği üretir.
- **İBB'nin tutmadığı tarihçeyi tutar.** "Bu saatte genelde ne kadar dolu?", hat düzenliliği ve **ölçülmüş**
  varış tahmini hatası ancak böyle mümkün.
- **Sayı uydurmaz.** Her araç sonucu kaynak URL'si ve gözlem zamanı taşır; kayıtlı veriye "canlı" denmez;
  ajanın sadakat kontrolü araç çıktısında olmayan sayıyı kabul etmez; acil numaralar resmî listeyle
  karşılaştırılır.
- **Gizlilik baştan:** konum sunucuda tutulmaz; sağlık ifadeleri kuyruğa, günlüğe ve modele gitmeden
  gizlenir; hesap silme bütün depolarda tek zincirdir.

**Durum (28 Eylül 2026, `main` = `c568f84`):** her şey dizüstünde çalışıyor, hiçbir şey deploy edilmedi.
Vatandaş uygulaması, operatör konsolu, 18 MCP aracı ve modelsiz ajan çalışıyor; gerçek model yolu bağlı ama
henüz gerçek bir modelle ölçülmedi. Azure Maps, Azure Speech ve Microsoft girişi anahtar gelene kadar kapalı
ve ekranda "bağlı değil" yazar. Test ve eval sayıları yukarıdaki *Sayılar* tablosunda, kaynağı
`eval/results/numbers.md`. Günlük plan [docs/SPRINT.md](docs/SPRINT.md), kurallar [AGENTS.md](AGENTS.md),
mühendislik [docs/ENGINEERING.md](docs/ENGINEERING.md), tehdit modeli [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md),
kararlar [DECISIONS.md](DECISIONS.md), MCP kurulumu [docs/mcp-usage.md](docs/mcp-usage.md).

**Sonuçlar** yukarıdaki *Results* tablosundadır ve her sayı `eval/results/` ya da `data/reference/`
altındaki bir dosyadan kopyalanır. Otobüs varış tahmininin ölçülmüş hatası **12,94 dk** (1.351 tahmin,
ayarlanmamış 120 sn/durak); 13 Eylül'de kalibre edilen saat dilimi oranlarının 11,16 dk'lık değeri örneklem içi
uyumdur (tek 235 sn/durak oranınınki 12,37 dk), eğitimde görülmeyen 523 tahminde 35,82 dk'ya çıkıyor; yani
kalibrasyon tahmini kötüleştiriyor (`eval/results/eta.md`). Bu yüzden 23 Eylül'den beri araçlar ayarlanmamış
120 sn/durak oranını kullanıyor; kalibre oranlar yalnızca `NABIZ_ETA_PROFILE_MODE=calibrated` ile açılır
(DECISIONS #18).

**Sınırlar:** otobüs varış saatleri tahmindir ve henüz yeterince iyi değildir · mod karşılaştırması
navigasyon değildir · tarihçe ince (otopark profilinde yeterli hücre yok, hat düzenliliği iki gün) · 38 değil
28 hava kalitesi istasyonu · PM2.5 yok · yayımlanan AQI 24 saatlik yürüyen ortalamadır · İSBİKE servisi
kapalı · trafik yoğunluk veri seti Ocak 2025'te durdu · İSPARK verisi ~10 dakikada bir güncellenir · ücretsiz
ADX kümesinin SLA'sı yoktur. Tam liste yukarıdaki *Limitations* bölümünde.

---

## Licence and attribution

- **Code:** MIT, see [LICENSE](LICENSE).
- **Data:** İBB Open Data Licence (CC BY 4.0). *Contains public sector information from the İstanbul
  Metropolitan Municipality Open Data Portal.* Licence text: <https://data.ibb.gov.tr/license>.
- **Attribution, personal-data handling (bus number plates are dropped at the parsing boundary), and the
  politeness policy toward İBB's services:** [NOTICE.md](NOTICE.md).
- **No İBB, İETT, İSPARK or Metro İstanbul logo, emblem or other brand element is used anywhere in this
  project.** Organisation names appear only to attribute the source of the data.

## Acknowledgements

İBB's Department of Information Technologies and the Open Data Portal team publish these services openly
and without registration; this project exists because of that. Thanks also to İETT, İSPARK, Metro İstanbul
and the İBB Traffic Control Centre, whose services stand behind every answer here.

Built for **Microsoft AI Innovators**. Plan: [PLAN.md](PLAN.md) · Sprint: [docs/SPRINT.md](docs/SPRINT.md) ·
Decisions: [DECISIONS.md](DECISIONS.md) · MCP setup: [docs/mcp-usage.md](docs/mcp-usage.md).
