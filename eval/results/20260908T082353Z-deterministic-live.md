# Eval results — 2026-09-08T08:23:53+00:00

`mode=deterministic` · `live` · data source: live İBB endpoints · 13/24 scenarios run, 11 skipped · upstream requests to İBB: 8

## Results

| Metric | Result | How it is measured |
|---|---|---|
| Task success rate | 13/13 (100.0%) | journey scenarios from `eval/journeys.jsonl` (24 selected, 13 run); a scenario passes when every tool call returns (or refuses exactly where it should) and every required field is present |
| Bus ETA mean absolute error | n/a (no observed arrivals logged yet: the collector must run for several days before a prediction can be paired with the arrival it predicted) | `eta_log` — every estimate is written with its method; the collector marks the vehicle's real arrival at that stop; MAE over those pairs |
| Numeric faithfulness | n/a (deterministic mode generates no answer text) | share of the free-standing numbers in the answer that appear in a tool result or in the question; `PM10`, `500T` and timestamps are names, not claims, and an ambiguous `1.250` is allowed either the Turkish (1250) or the English (1.25) reading |
| Tool-call accuracy | n/a (the harness calls the expected chain itself; only an agent can pick the wrong tool) | called chain vs. the scenario's `expected_tools` |
| p95 end-to-end latency | 17652 ms | sum of the scenario's tool calls, cache shared across scenarios, live network — a cold-cache call also waits out the client's own ≥6 s per-host spacing, so this is politeness plus İBB, not İBB alone |
| Data freshness at answer time | 32 s median, 1033.9 h p95 | age of the reading itself (`provenance.reported_at`) over the 5 of 19 calls whose source stamps its data; a metro notice is stamped when it was issued, so it is legitimately days old while the read is seconds old — see 'Freshness by source' |

## Data layer

| Metric | Result |
|---|---|
| Tool success rate | 19/19 (100.0%) |
| Required fields present | 73/73 (100.0%) |
| Optional checks not applicable | 4 of 77 |
| Provenance present (calls that returned data) | 17/17 (100.0%) |
| Of those, carrying an upstream timestamp | 5/17 (29.4%) |
| Number-plate leaks | 0 |
| p50 scenario latency | 17 ms |
| Forbidden-phrase violations | n/a (no generated answer in this mode) |
| Tokens / cost | n/a (no provider usage reported) |

## Freshness by source

| Source | Calls | Median age | Oldest |
|---|---|---|---|
| `iett_line` | 3 | 32 s | 32 s |
| `metro_status` | 1 | 1033.9 h | 1033.9 h |
| `traffic` | 1 | 24.3 min | 24.3 min |

## Per journey

| Journey | Passed |
|---|---|
| J1 | 6/6 (100.0%) |
| J2 | 6/6 (100.0%) |
| J3 | 1/1 (100.0%) |

## Per tool

| Tool | Calls | OK | p50 | p95 |
|---|---|---|---|---|
| `iett_line_buses` | 2 | 2 | 0 ms | 5169 ms |
| `iett_next_arrivals` | 3 | 3 | 15 ms | 7094 ms |
| `iett_stops_search` | 3 | 3 | 2 ms | 313 ms |
| `ispark_find_parking` | 5 | 5 | 7 ms | 17652 ms |
| `ispark_typical_occupancy` | 1 | 1 | 1 ms | 1 ms |
| `metro_status` | 1 | 1 | 4594 ms | 4594 ms |
| `places_resolve` | 3 | 3 | 2 ms | 2 ms |
| `traffic_index` | 1 | 1 | 6979 ms | 6979 ms |

## Error taxonomy

| Kind | Count |
|---|---|
| `refused_as_expected` | 2 |

## Scenarios

| id | lang | journey | Result | Latency | Note |
|---|---|---|---|---|---|
| `j1-tr-1` | tr | J1 | pass | 519 ms |  |
| `j1-en-1` | en | J1 | pass | 10 ms |  |
| `j1-tr-2` | tr | J1 | pass | 17652 ms |  |
| `j1-en-2` | en | J1 | pass | 1 ms |  |
| `j1-tr-3` | tr | J1 | pass | 6984 ms |  |
| `j1-en-3` | en | J1 | pass | 6 ms |  |
| `j2-tr-1` | tr | J2 | pass | 5169 ms |  |
| `j2-en-1` | en | J2 | pass | 7406 ms |  |
| `j2-tr-2` | tr | J2 | pass | 17 ms |  |
| `j2-en-2` | en | J2 | pass | 12 ms |  |
| `j2-tr-3` | tr | J2 | pass | 2 ms |  |
| `j2-en-3` | en | J2 | pass | 0 ms |  |
| `j3-tr-1` | tr | J3 | pass | 4594 ms |  |
| `j3-en-1` | en | J3 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j3-tr-2` | tr | J3 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j3-en-2` | en | J3 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j3-tr-3` | tr | J3 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j3-en-3` | en | J3 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j4-tr-1` | tr | J4 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j4-en-1` | en | J4 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j4-tr-2` | tr | J4 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j4-en-2` | en | J4 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j4-tr-3` | tr | J4 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |
| `j4-en-3` | en | J4 | skipped | 0 ms | skipped: upstream budget of 8 requests spent |

---

Harness `eval/run_eval.py` · scenarios `eval/journeys.jsonl` · commit `21d3cb4` · Python 3.12.13 · finished 2026-09-08T08:24:35+00:00

Contains public sector information from the İstanbul Metropolitan Municipality Open Data Portal, licensed under the İBB Open Data Licence (CC BY 4.0).
