# ETA accuracy

606 of 2257 predictions resolved (26.8%); 1651 vehicles were never observed at the target stop within 90 minutes.

| Metric | Value |
|---|---|
| Mean absolute error | 16.56 min |
| Median absolute error | 14.66 min |
| Bias (positive = predicted late) | -11.67 min |
| p90 absolute error | 34.78 min |
| Within 2 minutes | 9.2% |
| Within 5 minutes | 20.8% |
| Sample size | 606 |

## By method

| Method | n | MAE (min) | Within 2 min | Within 5 min |
|---|---|---|---|---|
| `distance` | 106 | 15.29 | 6.6% | 26.4% |
| `stop_sequence` | 500 | 16.83 | 9.8% | 19.6% |

## How this is measured, and what limits it

- Arrivals are observed by the collector's watched-line tick, so they are located to within 3 minutes. A perfect predictor would still show a mean absolute error near 1.5 minutes.
- A vehicle that passes a stop between two ticks is never observed there; its predictions stay unresolved rather than being counted as wrong.
- İETT reports the *nearest* stop, not a stop event, so a bus held in traffic beside a stop registers as arrived slightly early.

İBB publishes no arrival feed, so this is the best ground truth available. The numbers above are honest about that rather than quoting a figure the method cannot support.

## Diagnosis: model error or measurement error?

| Line | n | current 120 s/stop | best rate alone | best constant + rate |
|---|---|---|---|---|
| 500T | 500 | 16.8 min | 235 s/stop -> 12.4 min | 11.5 min + 150 s/stop -> 10.2 min |

- **500T: the rate is tunable.** 235 s/stop would cut the error.
