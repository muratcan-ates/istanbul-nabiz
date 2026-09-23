# ETA accuracy

1351 of 6801 predictions resolved (19.9%); 5450 vehicles were never observed at the target stop within 90 minutes.

| Metric | Value |
|---|---|
| Mean absolute error | 12.94 min |
| Median absolute error | 11.24 min |
| Bias (positive = predicted late) | -0.43 min |
| p90 absolute error | 29.03 min |
| Within 2 minutes | 14.1% |
| Within 5 minutes | 27.3% |
| Sample size | 1351 |

## By method

| Method | n | MAE (min) | Within 2 min | Within 5 min |
|---|---|---|---|---|
| `distance` | 111 | 15.16 | 6.3% | 26.1% |
| `stop_sequence` | 1240 | 12.74 | 14.8% | 27.4% |

## How this is measured, and what limits it

- Arrivals are observed by the collector's watched-line tick, so they are located to within 3 minutes. A perfect predictor would still show a mean absolute error near 1.5 minutes.
- A vehicle that passes a stop between two ticks is never observed there; its predictions stay unresolved rather than being counted as wrong.
- İETT reports the *nearest* stop, not a stop event, so a bus held in traffic beside a stop registers as arrived slightly early.

İBB publishes no arrival feed, so this is the best ground truth available. The numbers above are honest about that rather than quoting a figure the method cannot support.

## Diagnosis: model error or measurement error?

| Line | n | current 120 s/stop | best rate alone | best constant + rate |
|---|---|---|---|---|
| 15F | 62 | 7.0 min | 125 s/stop -> 7.0 min | 0.0 min + 120 s/stop -> 7.0 min |
| 34 | 6 | 1.7 min | 95 s/stop -> 1.6 min | 2.0 min + 70 s/stop -> 1.5 min |
| 500T | 1172 | 13.1 min | 80 s/stop -> 11.3 min | 8.0 min + 50 s/stop -> 10.4 min |

- **15F: the rate is tunable.** 125 s/stop would cut the error.
- **34: the rate is tunable.** 95 s/stop would cut the error.
- **500T: the rate is tunable.** 80 s/stop would cut the error.

---

*Everything above this line is the output of*
`NABIZ_OFFLINE=1 .venv/bin/python scripts/eta_report.py --diagnose`, *run on 2026-09-23 against the
local lake: 6,801 logged predictions and 10,851 line-snapshot rows collected between 2026-09-08 17:30
and 2026-09-22 21:17 UTC. No network call was made. The lake is gitignored, so these figures cannot be
re-derived from a fresh clone. Everything below is written by hand; `scripts/eta_report.py` rewrites
the whole file when re-run, so carry these sections over.*

## Read this before quoting a number

### Every logged prediction used the untuned 120 s/stop

The calibrated profile from commit `c306157` (`data/reference/eta_profile.json`) is read by the
`iett_next_arrivals` tool, but not by the collector: `build_eta_predictions` in
`scripts/collect_forever.py` calls `estimate_arrivals` with `EtaParams(max_results=6)` and no
`speed_profile`. All 1,590 stop-sequence predictions logged since `c306157` imply exactly 120 s/stop
(`eta_minutes * 60 / stops_away`). **No estimate made with the calibrated rates has ever been
measured**; the 12.94 minutes above is the untuned estimator.

### Before and after `c306157`, as logged (120 s/stop throughout)

| Predictions made | Logged | Resolved | MAE | Median | Bias | Within 5 min |
|---|---|---|---|---|---|---|
| before 2026-09-13 15:18:55 UTC | 2,533 | 662 | 15.84 min | 13.83 min | -10.32 min | 21.9% |
| since | 4,268 | 689 | 10.16 min | 9.13 min | +9.07 min | 32.5% |

The drop is **not** the calibration (see above). It coincides with a change in *what* is measured:
when the collector restarted at 2026-09-13 14:46 UTC its ETA targets moved from two 500T stops
(224661 KARAKAYA, 301341 4.LEVENT METRO) to three other 500T stops (205501, 206042, 261262) plus two
15F stops (219532, 260141) and one 34 stop (900121). Different stops, different spacing, different error.
The bias even changes sign, from predicting too early to predicting too late.

### Held-out replay of the calibrated profile

Question: had the calibrated rates been used, would the estimates have been better?

Method: every stop-sequence prediction made after the profile was fitted (`generated_at`
2026-09-13 15:30:15 UTC) is re-timed as `stops_away * rate / 60`, with the rate chosen by
`EtaProfile.seconds_per_stop_for` exactly as the tool chooses it, and scored with the same pairing as
`eta_report.score`. A prediction counts only when its 90-minute match window is fully covered by
collector ticks (no gap over 10 minutes), so the collection gap from 2026-09-14 03:48 to 2026-09-22
19:12 UTC cannot right-censor the sample. The same replay run on the profile's own training rows
reproduces the fit's figures exactly (n = 500, 16.83 -> 11.16 min), so the mechanics are the tool's.
The replay is `scripts/eta_holdout.py` (`make eta-holdout`); re-run on 2026-09-23 it printed the same
n = 523, 10.18 and 35.82 min. It reads the gitignored local lake, so these figures cannot be re-run
from a clone.

| Held-out predictions | n | Logged, 120 s/stop | Calibrated profile |
|---|---|---|---|
| All | 523 | 10.18 min (bias +9.1) | 35.82 min (bias +35.6) |
| 500T, evening cell (445 s/stop) | 175 | 7.85 min | 64.62 min |
| 500T, night cell (160 s/stop) | 310 | 12.14 min | 21.70 min |
| 15F, global rate (235 s/stop) | 32 | 5.61 min | 20.54 min |
| 34, global rate (235 s/stop) | 6 | 1.73 min | 6.54 min |

**On data it was not fitted on, the calibrated profile makes the estimate about 3.5 times worse.**
The target change explains why. The profile was fitted only on predictions for KARAKAYA and
4.LEVENT METRO, where a bus took a median 283-379 s per remaining stop; at the three new 500T targets
it took 63-93 s (medians over resolved stop-sequence predictions). Seconds per stop is a property of
the stretch of road, not of the line, and a per-line rate fitted on two stops does not transfer.

Limits of this replay:

- It is a replay, not a live measurement. It re-times the buses the collector actually logged; with
  the calibrated rate the engine's top-6 cut could have kept a slightly different set.
- 485 of the 523 rows are 500T, all from one evening and one night (13-14 Sep). The 34 row (n = 6) is
  too small to mean anything.
- It shows the calibration does not generalise to other stops. It does not show what a better model
  would score.

### What 12.37 and 11.2 are

Both are **in-sample fits**, not measured accuracy: the error of the fitted rates on the same 500
predictions they were fitted on (500T only, 8 and 13 Sep, the two old target stops).

- **12.37 min**: one 235 s/stop rate for 500T (`overall.mae_minutes` in `data/reference/eta_profile.json`).
- **11.2 min**: the per-bucket cells, weighted by their samples:
  (6.58 x 57 + 11.52 x 342 + 12.54 x 101) / 500 = 11.16.
- The fit's own out-of-sample check, leave one clock hour out, gave about 11.7 min (docstring of
  `src/ibb_mcp/eta_profile.py`), still on the same two stops. The replay above is the first test on
  stops the fit never saw.

### History

| Recorded in | Date | Resolved | MAE | Note |
|---|---|---|---|---|
| `586c110` | 2026-09-08 | 0 of 12 | none | collector had just started |
| `3d35602` | 2026-09-08 | 5 of 48 | 2.89 min | too few to mean anything |
| `f3c842f` | 2026-09-13 | 161 of 721 | 16.66 min | the "16.7 min on 161" in the dated §3 table of `docs/NABIZ.md` |
| `0951bcc` | 2026-09-13 | 606 of 2,257 | 16.56 min | the README's "16.6 min (n = 606)" |
| `c306157` | 2026-09-13 | 607 of 2,318 | 16.54 min | bias -11.65 min; the report the calibration commit shipped with |
| this file | 2026-09-23 | 1,351 of 6,801 | 12.94 min | first report to include predictions at the new targets |

The `c306157` version's diagnosis read: 500T, n = 501, 16.8 min at 120 s/stop; 235 s/stop alone
-> 12.4 min; 11.5 min + 150 s/stop -> 10.2 min. On today's lake the same diagnosis wants 80 s/stop for
500T (table above), which is the non-transfer again, seen from the other side.
