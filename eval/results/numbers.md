# Numbers sheet

Measured 2026-09-26T03:55:46Z · working tree over commit `4471693` · Python 3.12.3 · NABIZ_SPRINT_MODE=1 (DECISIONS #29) · `NABIZ_OFFLINE=1 .venv/bin/python scripts/demo_numbers.py --write`

| Number | Value | Command |
|---|---|---|
| MCP tools | 17 | build_server().list_tools(), offline |
| Tests collected | 2168 | pytest --collect-only -q |
| Tests passed | 2163 | pytest -q (NABIZ_OFFLINE=1 NABIZ_LLM_NO_PROBE=1 NABIZ_SPRINT_MODE=1) |
| Tests failed | 1 | same |
| Tests skipped | 1 | same |
| Tests xfailed | 3 | same |
| Eval scenarios in eval/journeys.jsonl | 72 | eval/run_eval.py --offline |
| Eval scenarios run (deterministic, offline) | 60 | same |
| Eval scenarios skipped (agent-only) | 12 | same |
| Eval scenarios passed | 49 | same |
| Knowledge questions validated | 100 | eval/run_knowledge_eval.py --offline |
| Knowledge retrieval accuracy | n/a (offline: fixed unknown answers, retrieval not measured) | same |

Tools: air_quality_forecast, air_quality_now, check_alerts, city_freshness, ibb_services_search, iett_line_buses, iett_next_arrivals, iett_stops_search, ispark_find_parking, ispark_typical_occupancy, line_reliability, metro_equipment_status, metro_station_info, metro_status, places_resolve, plan_journey, traffic_index
