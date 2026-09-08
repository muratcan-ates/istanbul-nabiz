# ETA accuracy

5 of 48 predictions resolved (10.4%); 43 vehicles were never observed at the target stop within 90 minutes.

| Metric | Value |
|---|---|
| Mean absolute error | 2.89 min |
| Median absolute error | 2.25 min |
| Bias (positive = predicted late) | -1.6 min |
| p90 absolute error | 4.65 min |
| Within 2 minutes | 40.0% |
| Within 5 minutes | 80.0% |
| Sample size | 5 |

## By method

| Method | n | MAE (min) | Within 2 min | Within 5 min |
|---|---|---|---|---|
| `distance` | 1 | 2.25 | 0.0% | 100.0% |
| `stop_sequence` | 4 | 3.05 | 50.0% | 75.0% |

## How this is measured, and what limits it

- Arrivals are observed by the collector's watched-line tick, so they are located to within 3 minutes. A perfect predictor would still show a mean absolute error near 1.5 minutes.
- A vehicle that passes a stop between two ticks is never observed there; its predictions stay unresolved rather than being counted as wrong.
- İETT reports the *nearest* stop, not a stop event, so a bus held in traffic beside a stop registers as arrived slightly early.

İBB publishes no arrival feed, so this is the best ground truth available. The numbers above are honest about that rather than quoting a figure the method cannot support.
