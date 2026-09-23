# Route advisor — `plan_journey`

> What is on `main` after the `feat/route-advisor` worktree was harvested on 2026-09-23.
> Every number below says where it came from: a file in this repository, a test, or a command
> run on 2026-09-23 and named here. A number nobody could source was left out, and §8 says which.

---

## 1. What it answers, and what it is not

The question is the one an İstanbullu asks before leaving the house:

> *"Trafik böyleyken arabayla mı gitsem, metroyla mı?"*

`plan_journey` compares four modes between two points — drive, metro/rail, one İETT bus line,
walk — and returns, for each, minutes built from named legs, a comfort score with its arithmetic,
a confidence level, every assumption it used, and notes. A mode it cannot cost comes back in
`unavailable_options` with a Turkish reason, because "too far to walk" or "no single bus line
joins these two ends" is itself an answer.

It is a **comparison, not navigation** (PLAN.md §17 keeps route planning out of the project):

* no road network, turn geometry or live incidents — driving is straight-line distance times a
  winding factor, at a speed derived from one city-wide traffic number;
* no timetable for rail and no departure board — it never says "board the 08:41";
* no bus transfers — one line or nothing;
* no Metrobüs as a rail mode and no ferry — neither is in the data it reads.

The payload says so itself: `kind: "estimate"` and a Turkish disclaimer travel with every answer
(`routing.DISCLAIMER_TR`).

---

## 2. Inputs

| Input | Read through | What it contributes | Cost on the shared gateway |
|---|---|---|---|
| Traffic index, `TrafficIndexHistory/1/H` | `TrafficSource.current()` | The drive speed; the reading being judged | Shared with `traffic_index`; cached 300 s (`cache.py`) |
| Traffic history, `TrafficIndexHistory/28/H` | `Nabiz.traffic_baseline()` | The weekday × hour norm (§6) | One request per 6 h per process, 15 min back-off after a failure |
| Metro İstanbul `GetStations` | `MetroSource.stations()` | The rail graph (§4) | Cached for a day (`STATIONS_TTL`) |
| Metro İstanbul `GetServiceStatuses` | `MetroSource.service_status()` | Disruption penalty on the lines the path rides | Shared with `metro_status` |
| İSPARK `/ispark/Park` | `IsparkSource.find_near()` | Parking search time at the destination | Shared with `ispark_find_parking` |
| İETT GTFS stop sequences | `Nabiz.stop_sequences()` / `stop_routes()` | Which single line runs the right way (§5) | None: a local export, gitignored |
| İETT planned departures | `IettSource.schedule()` | Headway of the one line that is costed | One İETT request per line per day (`SCHEDULE_TTL_SECONDS`) |
| `data/reference/eta_profile.json` | `eta_profile.load_profile()` | Seconds per stop for that line | None |

The charter records the history endpoint serving 30 days hourly (`docs/NABIZ.md`, verified
2026-09-08); 28 days is used so every weekday × hour cell gets four samples. No input opens a new
per-user path to İBB (DECISIONS #3): everything goes through `PoliteClient` and the TTL cache.

Without `data/reference/gtfs` the bus option is withdrawn with a reason and the rest still
answers. Without the traffic history the `traffic_typical` reading says the comparison is
unavailable. An unread metro notice feed or İSPARK list is reported as unknown, never as
"no disruption" or "no free space" (§7).

### Modules

| Module | Role |
|---|---|
| `src/ibb_mcp/routing.py` | `compare_options`: fetches the live readings, builds the four options, keeps the honesty contract (every leg names the reading or assumption behind its minutes). |
| `src/ibb_mcp/metro_graph.py` | The rail network as a graph: Dijkstra over seconds, transfers only where distance allows, the Marmaray tube as caller-supplied rows. No I/O. |
| `src/ibb_mcp/lines.py` | `StopRouteIndex`: stop → route variants, line names parsed from route codes, and the one direction-aware "origin before destination on the same variant" scan in the project. No I/O. |
| `src/ibb_mcp/traffic_profile.py` | Weekday × hour median of the traffic index, and the comparison of one reading against it. No I/O. |
| `src/ibb_mcp/tools.py` | `Nabiz.plan_journey` and `traffic_index`; builds the stop index once, memoises the traffic baseline. |
| `src/ibb_mcp/server.py` | Registers `plan_journey` like every other tool (`@mcp.tool()` then `@tool`). Tool count stays 15. |

---

## 3. The four options

**Drive.** Straight-line distance × `road_winding` 1.35 (the same constant as `eta.EtaParams`),
at a speed on a straight line from 48 km/h at index 1 to 9 km/h at index 99 — 24.5 km/h at the
index 60 recorded in `tests/fixtures/traffic_index_1h.json` (`test_the_speed_curve_hits_its_documented_anchors`).
A Bosphorus crossing goes over whichever of three fixed bridges gives the shortest two-leg
distance, plus a queue scaled by the live index. Parking: the nearest open İSPARK lot with a
free space within 0.8 km costs 2–10 minutes by how full it is, plus the walk from it; no such
lot costs a 15-minute search. None of these constants has been fitted to a measured car
journey — the project collects none — so the drive option is never better than `medium`
confidence once a bridge or a parking guess is involved.

**Metro / rail.** Walk to a platform, wait half an assumed 6-minute headway, ride the graph,
walk off. §4 has the graph.

**Bus.** The single İETT line whose stop order passes a stop within 0.8 km of the origin *before*
one within 0.8 km of the destination (24 candidate stops per end). Candidates are ranked by walk
+ ride minutes, not stop count alone. The chosen line is priced with its calibrated seconds per
stop from `eta_profile.json` — fitted on the project's own arrivals, labelled in-sample, and an
upper bound for a ride (see `eta_profile.py`) — and a headway read from its planned departures
±60 minutes around now. Up to four other lines that also run the right way are listed in
`detail.other_direct_lines` with where to board, where to get off and how many stops, and
**without minutes**: a duration needs each line's own rate and timetable, and every extra
timetable is one more request on İETT's 100-an-hour budget.

**Walk.** Same side of the Bosphorus and at most 2.5 km of winding-corrected distance.

`fastest_mode` and `most_comfortable_mode` rank the costed options. They rank estimates, which
is why `kind: "estimate"`, the disclaimer and every assumption travel with them.

---

## 4. The rail graph

`MetroGraph.from_stations` turns Metro İstanbul's station list into a graph:

* **Ride edges** join neighbours in `Order` along a line, both ways: great-circle distance at 35
  km/h (metro), 17 (tram) or 12 (funicular, codes `F…`/`TF…`), plus 25 s dwell per stop.
* **Transfer edges** exist only where distance justifies one: platforms within 250 m are one
  station (4-minute transfer); a walk up to 800 m is allowed between stations sharing a name and
  up to 350 m between differently named ones, at the advisor's own walking pace.
* **Rejected transfers** — same-name pairs beyond 800 m — are kept in `rejected_transfers`.

On the recorded list (`tests/fixtures/metro_stations.json`): 248 rows, 245 with coordinates,
18 lines; the 3 without coordinates are dropped and counted (`test_graph_loads_every_usable_station_and_line`).

### The phantom transfer

Matching transfers by station name looks safe because Metro İstanbul's names are clean. It is
not: 25 names repeat across lines, forming 33 cross-line pairs, and 8 of those pairs are more
than 800 m apart (counted on the fixture, 2026-09-23):

| Name | Lines | Distance |
|---|---|---|
| Bahariye | M9 / T3 | 20.677 km |
| Çarşı | M5 / T3 | 7.798 km |
| Yenimahalle | M3 / T4 | 6.991 km |
| Yenimahalle | M3 / M7 | 6.799 km |
| Yenimahalle | M7 / T4 | 3.096 km |
| Sağmalcılar | M1A / T4, M1B / T4 | 1.827 km each |
| Bostancı | M4 / M8 | 1.628 km |

Trust every shared name and Kadıköy → Taksim becomes a 64-minute rail journey that crosses the
Bosphorus at Bahariye (T3 in Kadıköy, M9 in Bağcılar) and changes again between the two
Yenimahalle stations — reproduced by `test_the_phantom_is_real_when_names_are_trusted`. A phantom
edge is worse than a missing one: it produces a confident, plausible number instead of "no path".
Rejecting every shared name is wrong too: Aksaray M1A/T1 is 557 m apart and a real walking
interchange, and it survives (`test_every_rejected_transfer_is_a_shared_name_beyond_walking_range`).

### Crossing the water: the Marmaray tube

Metro İstanbul's feed has no rail link between the two sides, so the graph built from the feed
alone answers Kadıköy → Taksim with `disconnected` (`test_kadikoy_to_taksim_has_no_rail_path`).
The advisor adds one line it vouches for: `marmaray_tube()` places four Marmaray rows on stations
the feed already has — Yenikapı (M1A, M1B, M2), Sirkeci (T1), Üsküdar (M5), Ayrılık Çeşmesi (M4),
the anchors the advisor used before the graph existed — and the ordinary distance rule turns each
shared coordinate into an in-station transfer. Only the tube is modelled; Marmaray's suburban
stretches reach stations the feed does not carry. The rows have no `station_id`, the graph names
them in `added_lines`, and an option that uses them says so: the `marmaray_tube` assumption, one
confidence notch, and a note that Marmaray notices are not in Metro İstanbul's feed.
`RoutingParams(include_marmaray=False)` turns it off, and the crossing is refused again
(`test_without_the_marmaray_rows_the_water_cannot_be_crossed_by_rail`).

Offline, `plan_journey(origin="Taksim", destination="Kadıköy")` rides M2 to Yenikapı, Marmaray
to Ayrılık Çeşmesi and M4 to Kadıköy: 44.4 minutes, 2 transfers, confidence `medium`, against a 56.9-minute drive over
the 15 Temmuz Şehitler Köprüsü at confidence `low` (the recorded fixtures, run through
`Nabiz.plan_journey` with GTFS sealed off, 2026-09-23).

### Why a graph instead of the straight line it replaced

Before the harvest, `main` costed rail as the straight line between the nearest station at each
end, with no transfer when some nearby pair shared a line and exactly one otherwise. Over the
16,370 same-side station pairs more than 2.5 km apart that have a rail path, that rule gave the
graph's transfer count in 7,224 and **too few transfers in 9,145** (computed on the recorded
station list, 2026-09-23). It also never checked that the two lines meet at all. The graph
answers with the lines actually ridden — `detail.lines`, one `rail` leg per line
(`"M2: Taksim → Yenikapı, 4 durak"`) and one `transfer` leg per change — so the agent can read
the itinerary off the legs without inventing it.

### Disruptions

A notice counts against the metro option when it is live (`IsActive` not false) and its line
code — the first token of `LineName`, folded (`"M7 Yıldız-Mahmutbey"` → `M7`) — is a line the
path rides, **anywhere** on the path, not only at either end
(`test_a_notice_on_a_line_in_the_middle_of_the_path_counts`). The penalty is 10 minutes, once. A
notice whose name does not fold to a line code is reported as unplaceable instead of dropped; a
retired notice costs nothing.

---

## 5. Buses: one scan, in `lines.py`

`StopRouteIndex` inverts the GTFS stop sequences once per process and answers two questions:
which lines call at a stop (used by `iett_next_arrivals`' refusal hint) and which lines ride from
any stop in one set to any stop in another **in that order** (used by the bus option). Direction
is the whole point: 500T runs Şifa Sondurak → 4. Levent Metro over 64 stops as `500T_G_D0` and
back over 66 as `500T_D_D0` (`tests/test_lines.py`, on the committed `gtfs_mini` cut).

Line names are read from the route code (`500T_G_D0` → `500T`). For all 2,869 sequence variants
whose code parses, that equals `routes.csv`'s `route_short_name`, with zero differences; the 7 of
2,876 whose code is a shifted column of Turkish prose (23 such rows in `routes.csv`, 9,256 of
9,279 well formed) are never offered (`test_a_route_code_that_names_no_line_is_never_offered`).
Measured on the local export, 2026-09-23: 24.5 ms to build the index (median of 7), 14,017
stop codes, and a median 0.49 ms for a Kartal → 4.Levent scan (20 runs).

---

## 6. "Is traffic worse than usual?" — the weekday × hour norm

İBB's traffic index is one city-wide number. The one driving claim the project can stand behind
beyond it is "the index now is N; at this hour on this weekday it has measured M".
`traffic_profile.build_baseline` takes the median of each İstanbul-local weekday × hour cell of
the 28-day history, leaving out the last 24 hours so the reading being judged does not vote in
its own norm. A cell with fewer than 3 samples says nothing; the comparison then comes back as
`unknown` and states how many samples it has and needs. Bands (±10 %, ±25 %, at least 3 points)
are assumptions, documented in the module, and only choose words: the delta and the ratio travel
beside them.

It reaches the user twice: `plan_journey` adds a `traffic_typical` reading and, when the hour is
measurably heavier or lighter, a note on the drive option — without changing the minutes, since
the live index already set the speed — and `traffic_index(window="now")` adds a `typical` block.
Both cite the history read they came from: `plan_journey` lists its stamp in `data.provenance` and
gives the `traffic_typical` reading its age, and the `typical` block carries its own `provenance`. The
history does not age `plan_journey`'s envelope, which follows the live inputs the minutes rest on.

The norm is read from İBB's history rather than from the project's own lake because the lake is
too thin for it: `data/lake/traffic_index_hourly` held 18 distinct hourly points on 2026-09-23
(the collector keeps 3 per tick, `snapshots.TRAFFIC_HOURS`). The recorded fixture is one day,
so offline and in CI every comparison is `unknown` — which is the refusal path working, and is
what `tests/test_traffic_profile.py` asserts through the façade.

---

## 7. Honesty rules the tests hold

| Rule | Test |
|---|---|
| Every leg's minutes trace to a live reading or a named assumption | `test_every_option_explains_every_number_it_prints` |
| An unavailable option carries a reason and no numbers | `test_unavailable_options_carry_a_reason_and_no_numbers` |
| Unread metro notices are unknown, not all-clear | `test_unread_notices_are_unknown_not_all_clear` |
| Unread İSPARK is unknown, not full | `test_unread_parking_is_unknown_not_full` |
| A null traffic index (parsed as 0) withdraws the drive | `test_a_missing_traffic_index_withdraws_the_drive_instead_of_assuming_free_flow` (`tests/test_tools_extra.py`) |
| Runners-up are named, never timed | `test_other_direct_lines_are_named_but_not_timed` |
| The baseline never includes the reading it judges | `test_points_at_or_after_the_cutoff_do_not_vote` |
| No test reads `data/lake` or `data/reference/gtfs` | the `sealed` fixture in `tests/test_tools_extra.py`; see §10 |

---

## 8. Numbers checked, and numbers nobody has

* **Rail, one published check.** Metro İstanbul's own M7 card, recorded in the M7 notice in
  `tests/fixtures/metro_status.json`, gives a 36-minute one-way run over 17 stations; the graph
  gives 38.9 minutes Yıldız → Mahmutbey (`test_m7_end_to_end_lands_near_metro_istanbuls_published_36_minutes`).
  The same card gives a 4-minute peak headway where the advisor assumes 6 for every line and hour.
* **Rail, not carried over.** The worktree's notes compared Kartal → Kadıköy, Kartal → Sabiha
  Gökçen, Yenikapı → Taksim and Levent → Yenikapı against "about 40, 20, 9 and 20 real minutes".
  No source for those four is in the repository, so they are not claimed. The graph's own
  outputs for them are 41.6, 21.4, 9.8 and 20.9 minutes (recorded station list, 2026-09-23).
* **Drive.** No ground truth exists; the speed curve, winding factor, bridge queue and parking
  times are assumptions.
* **Bus.** The per-stop rate is an in-sample fit and an upper bound for a ride; see
  `src/ibb_mcp/eta_profile.py` and `eval/results/eta.md`.
* **Accuracy of `plan_journey` as a whole:** n/a (no measured door-to-door journey times exist in
  the project to score it against).

---

## 9. What came from `feat/route-advisor`, and what did not

The worktree at `../nabiz-advisor` (branch `feat/route-advisor`, cut from `401ab4b` on
2026-09-13) held uncommitted work. Everything of value is now on `main`; nothing there needs to
be kept.

| Worktree file | Outcome | Where it went, or why not |
|---|---|---|
| `src/ibb_mcp/metro_graph.py` | **Ported** | As is, plus caller-supplied rows (`added=`, `added_lines`), `marmaray_tube()`, and corrected docstring numbers (33 pairs / 25 names, 64-minute phantom, the M7 check). |
| `tests/test_metro_graph.py` | **Ported** | Plus the phantom reproduction, the M7 check and five Marmaray tests. |
| `src/ibb_mcp/lines.py` | **Ported** | Plus a caller-supplied `cost` for ranking and `in`; now the only direction-aware scan (routing's own loop was removed). |
| `tests/test_lines.py` | **Ported** | The real-data test ran only when a gitignored cache existed; it now runs on `tests/fixtures/gtfs_mini`. Cost-ranking and membership tests added. |
| `src/ibb_mcp/traffic_profile.py` | **Ported** | Plus the `before` cutoff; wired into `plan_journey` and `traffic_index`. |
| `tests/test_traffic_profile.py` | **Ported** | Plus the cutoff and four façade tests. |
| `src/ibb_mcp/advisor.py` | **Merged, file dropped** | A second advisor beside `routing.py`. Taken: line-code folding, the `IsActive` filter, unplaceable notices, notices on every line of the path, unread-is-unknown for notices and parking, the traffic-vs-norm signal, naming direct lines without timing them. Not taken: the drive/rail verdict that refuses to rank (the page renders `fastest_mode`), ±25 %/±10 % ranges, its own drive constants (45 km/h, weight 0.6) and summed parking within 1 km — `routing.py` keeps one set of each rather than two uncalibrated ones. |
| `tests/test_advisor.py` | **Merged, file dropped** | Its assertions re-expressed against `compare_options` in `tests/test_routing.py` (disruption on the ridden line only, retired and unread notices, unread parking, traffic above its norm). |
| `src/ibb_mcp/server.py` diff | **Dropped** | Three tools — `metro_route`, `iett_direct_lines`, `city_travel_compare` — all answered by `plan_journey` now (rail legs per line, `other_direct_lines`, the measured notes). Tool count stays 15. |
| `src/ibb_mcp/tools.py` diff | **Dropped** | Its graph cache is `routing.rail_graph`; its per-request 28-day history read (which also judged the reading against a norm containing it) is `Nabiz.traffic_baseline`, memoised with the cutoff; its 12-candidate bus search is routing's 24-candidate one. |
| `docs/route-advisor.md` | **Rewritten** | This file. Its proposed ADR is superseded by the one in the harvest handoff. |
| `data/reference/gtfs` | Nothing to port | An untracked symlink into `main`'s gitignored export. |

---

## 10. Running it

```bash
NABIZ_OFFLINE=1 .venv/bin/python -m pytest -q tests/test_routing.py tests/test_metro_graph.py \
    tests/test_lines.py tests/test_traffic_profile.py
```

These run on recorded fixtures and `tests/fixtures/gtfs_mini` only; the whole suite was also run
with `data/lake` and `data/reference/gtfs` made unreadable, with no test trying either. Offline,
the server answers `plan_journey` from the same fixtures (`ibb-mcp --offline`).

---

## 11. Limitations

* One city-wide traffic number: the drive estimate cannot know that your road is clear while the
  D-100 is not.
* Flat 6-minute headway for every rail line and hour; M7's own card says 4 at the peak.
* Marmaray is its tube only, at metro speed, with no notices; no Metrobüs, no ferry.
* One bus line or nothing; runners-up have no minutes.
* The weekday × hour norm needs İBB's history endpoint; offline it is always `unknown`.

---

Data: İBB Açık Veri Portalı, İBB Açık Veri Lisansı. Metro İstanbul station data and notices,
İETT GTFS, İSPARK occupancy and the İBB traffic index are published by their institutions. This
project is not affiliated with or endorsed by İBB, İETT, İSPARK or Metro İstanbul
([NOTICE.md](../NOTICE.md)).
