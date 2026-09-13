# ETA accuracy

161 of 721 predictions resolved (22.3%); 560 vehicles were never observed at the target stop within 90 minutes.

| Metric | Value |
|---|---|
| Mean absolute error | 16.66 min |
| Median absolute error | 16.37 min |
| Bias (positive = predicted late) | -3.95 min |
| p90 absolute error | 32.82 min |
| Within 2 minutes | 6.8% |
| Within 5 minutes | 17.4% |
| Sample size | 161 |

## By method

| Method | n | MAE (min) | Within 2 min | Within 5 min |
|---|---|---|---|---|
| `distance` | 46 | 22.61 | 0.0% | 8.7% |
| `stop_sequence` | 115 | 14.28 | 9.6% | 20.9% |

## How this is measured, and what limits it

- Arrivals are observed by the collector's watched-line tick, so they are located to within 3 minutes. A perfect predictor would still show a mean absolute error near 1.5 minutes.
- A vehicle that passes a stop between two ticks is never observed there; its predictions stay unresolved rather than being counted as wrong.
- İETT reports the *nearest* stop, not a stop event, so a bus held in traffic beside a stop registers as arrived slightly early.

İBB publishes no arrival feed, so this is the best ground truth available. The numbers above are honest about that rather than quoting a figure the method cannot support.

## Diagnosis: model error or measurement error?

| Line | n | current 120 s/stop | best rate alone | best constant + rate |
|---|---|---|---|---|
| 500T | 115 | 14.3 min | 165 s/stop -> 12.8 min | 17.0 min + 90 s/stop -> 8.8 min |

- **500T: the rate is tunable.** 165 s/stop would cut the error.
