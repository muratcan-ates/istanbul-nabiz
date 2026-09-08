# Eval results — 2026-09-08T08:42:28+00:00

`mode=deterministic` · `offline` · data source: recorded fixtures (tests/fixtures) · 24/24 scenarios run · upstream requests to İBB: 0

## Results

| Metric | Result | How it is measured |
|---|---|---|
| Task success rate | 24/24 (100.0%) | journey scenarios from `eval/journeys.jsonl` (24 selected, 24 run); a scenario passes when every tool call returns (or refuses exactly where it should) and every required field is present |
| Bus ETA mean absolute error | n/a (no observed arrivals logged yet: the collector must run for several days before a prediction can be paired with the arrival it predicted) | `eta_log` — every estimate is written with its method; the collector marks the vehicle's real arrival at that stop; MAE over those pairs |
| Numeric faithfulness | n/a (deterministic mode generates no answer text) | share of the free-standing numbers in the answer that appear in a tool result or in the question; `PM10`, `500T` and timestamps are names, not claims, and an ambiguous `1.250` is allowed either the Turkish (1250) or the English (1.25) reading |
| Tool-call accuracy | n/a (the harness calls the expected chain itself; only an agent can pick the wrong tool) | called chain vs. the scenario's `expected_tools` |
| p95 end-to-end latency | 28 ms | sum of the scenario's tool calls, cache shared across scenarios, fixtures, no network |
| Data freshness at answer time | 2.7 h median, 1034.2 h p95 | age of the reading itself (`provenance.reported_at`) over the 11 of 34 calls whose source stamps its data; a metro notice is stamped when it was issued, so it is legitimately days old while the read is seconds old — see 'Freshness by source' — offline this is the age of the recorded fixtures, not of live data |

## Data layer

| Metric | Result |
|---|---|
| Tool success rate | 34/34 (100.0%) |
| Required fields present | 142/142 (100.0%) |
| Optional checks not applicable | 6 of 148 |
| Provenance present (calls that returned data) | 32/32 (100.0%) |
| Of those, carrying an upstream timestamp | 11/32 (34.4%) |
| Number-plate leaks | 0 |
| p50 scenario latency | 2 ms |
| Forbidden-phrase violations | n/a (no generated answer in this mode) |
| Tokens / cost | n/a (no provider usage reported) |

## Freshness by source

| Source | Calls | Median age | Oldest |
|---|---|---|---|
| `aq_readings` | 4 | 2.7 h | 2.7 h |
| `iett_line` | 3 | 2.6 h | 2.6 h |
| `metro_status` | 3 | 1034.2 h | 1034.2 h |
| `traffic` | 1 | 2.7 h | 2.7 h |

## Per journey

| Journey | Passed |
|---|---|
| J1 | 6/6 (100.0%) |
| J2 | 6/6 (100.0%) |
| J3 | 6/6 (100.0%) |
| J4 | 6/6 (100.0%) |

## Per tool

| Tool | Calls | OK | p50 | p95 |
|---|---|---|---|---|
| `air_quality_forecast` | 3 | 3 | 2 ms | 2 ms |
| `air_quality_now` | 4 | 4 | 2 ms | 3 ms |
| `city_freshness` | 2 | 2 | 0 ms | 0 ms |
| `iett_line_buses` | 2 | 2 | 0 ms | 2 ms |
| `iett_next_arrivals` | 3 | 3 | 13 ms | 28 ms |
| `iett_stops_search` | 3 | 3 | 2 ms | 265 ms |
| `ispark_find_parking` | 5 | 5 | 1 ms | 2 ms |
| `ispark_typical_occupancy` | 1 | 1 | 0 ms | 0 ms |
| `metro_station_info` | 3 | 3 | 2 ms | 3 ms |
| `metro_status` | 3 | 3 | 0 ms | 0 ms |
| `places_resolve` | 4 | 4 | 1 ms | 1 ms |
| `traffic_index` | 1 | 1 | 1 ms | 1 ms |

## Error taxonomy

| Kind | Count |
|---|---|
| `refused_as_expected` | 2 |

## Scenarios

| id | lang | journey | Result | Latency | Note |
|---|---|---|---|---|---|
| `j1-tr-1` | tr | J1 | pass | 2 ms |  |
| `j1-en-1` | en | J1 | pass | 2 ms |  |
| `j1-tr-2` | tr | J1 | pass | 2 ms |  |
| `j1-en-2` | en | J1 | pass | 0 ms |  |
| `j1-tr-3` | tr | J1 | pass | 2 ms |  |
| `j1-en-3` | en | J1 | pass | 2 ms |  |
| `j2-tr-1` | tr | J2 | pass | 2 ms |  |
| `j2-en-1` | en | J2 | pass | 277 ms |  |
| `j2-tr-2` | tr | J2 | pass | 15 ms |  |
| `j2-en-2` | en | J2 | pass | 28 ms |  |
| `j2-tr-3` | tr | J2 | pass | 2 ms |  |
| `j2-en-3` | en | J2 | pass | 0 ms |  |
| `j3-tr-1` | tr | J3 | pass | 0 ms |  |
| `j3-en-1` | en | J3 | pass | 3 ms |  |
| `j3-tr-2` | tr | J3 | pass | 0 ms |  |
| `j3-en-2` | en | J3 | pass | 2 ms |  |
| `j3-tr-3` | tr | J3 | pass | 2 ms |  |
| `j3-en-3` | en | J3 | pass | 0 ms |  |
| `j4-tr-1` | tr | J4 | pass | 3 ms |  |
| `j4-en-1` | en | J4 | pass | 4 ms |  |
| `j4-tr-2` | tr | J4 | pass | 2 ms |  |
| `j4-en-2` | en | J4 | pass | 2 ms |  |
| `j4-tr-3` | tr | J4 | pass | 2 ms |  |
| `j4-en-3` | en | J4 | pass | 3 ms |  |

---

Harness `eval/run_eval.py` · scenarios `eval/journeys.jsonl` · commit `21d3cb4` · Python 3.12.13 · finished 2026-09-08T08:42:28+00:00

Contains public sector information from the İstanbul Metropolitan Municipality Open Data Portal, licensed under the İBB Open Data Licence (CC BY 4.0).
