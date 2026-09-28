# Numbers sheet

Measured 2026-09-28T14:02:40Z · working tree over commit `e5ab212` · Python 3.12.13 · NABIZ_SPRINT_MODE=1 (DECISIONS #29) · `NABIZ_OFFLINE=1 .venv/bin/python scripts/demo_numbers.py --write`

| Number | Value | Command |
|---|---|---|
| MCP tools | 18 | build_server().list_tools(), offline |
| Tests collected | 5285 | pytest --collect-only -q |
| Tests passed | 5255 | pytest -q (NABIZ_OFFLINE=1 NABIZ_LLM_NO_PROBE=1 NABIZ_SPRINT_MODE=1) |
| Tests failed | 0 | same |
| Tests skipped | 2 | same |
| Tests xfailed | 28 | same |
| Eval scenarios in eval/journeys.jsonl | 78 | eval/run_eval.py --offline |
| Eval scenarios run (deterministic, offline) | 66 | same |
| Eval scenarios skipped (agent-only) | 12 | same |
| Eval scenarios passed | 66 | same |
| Knowledge questions validated | 100 | eval/run_knowledge_eval.py --offline |
| Knowledge retrieval accuracy | n/a (offline: fixed unknown answers, retrieval not measured) | same |

Tools: air_quality_forecast, air_quality_now, check_alerts, city_freshness, ibb_datasets_search, ibb_services_search, iett_line_buses, iett_next_arrivals, iett_stops_search, ispark_find_parking, ispark_typical_occupancy, line_reliability, metro_equipment_status, metro_station_info, metro_status, places_resolve, plan_journey, traffic_index
