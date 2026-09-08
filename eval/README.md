# Evaluation harness

Every number in the README's **Results** section is written by `eval/run_eval.py` into
`eval/results/` and copied from there. Nothing in this directory estimates, rounds up, or
defaults a value: a metric that could not be computed is printed as `n/a (reason)`, because
a plausible-looking placeholder in a results table is worse than an admission.

```bash
.venv/bin/python eval/run_eval.py --selftest                          # scenario file + metric helpers
.venv/bin/python eval/run_eval.py --mode deterministic --offline      # 24 scenarios, no network
.venv/bin/python eval/run_eval.py --mode deterministic                # live İBB, budget-capped
.venv/bin/python eval/run_eval.py --mode agent --offline              # adds the answer-level metrics
.venv/bin/python eval/run_eval.py --mode agent --require-llm          # …and refuses to run without a model
```

Each run writes `eval/results/<timestamp>-<mode>-<offline|live>.json` (every call, every
field check, every latency) plus the same summary as `<timestamp>-<mode>-<offline|live>.md`,
and copies that summary over `eval/results/latest.md`, which is also printed to stdout.
`latest.md` is therefore whichever run went last; the committed one is deliberately the
**offline deterministic** run, because it is the only configuration that covers all 24
scenarios and reproduces on any machine with no network. A live run keeps its own dated
markdown beside its JSON rather than being the summary the README quotes. `--results-dir`
writes somewhere else entirely, which is how you try a selection without disturbing the
committed files. The exit code is `0` when every scenario passed, `1` when one failed, `2`
when the selection matched nothing and `3` when agent mode skipped.

## The two modes measure different things

**`--mode deterministic` (default)** drives `ibb_mcp.tools.Nabiz` directly with the tool
calls each scenario records. It measures the **data layer** — did the tool answer, does the
answer carry the fields the journey needs, is there provenance, how old is the reading —
and needs no LLM, so it runs in CI. It deliberately cannot measure two of the README rows:

* **Tool-call accuracy** is `n/a` here, because the harness itself calls the expected
  chain. Reporting 100% for a chain the harness chose would be a lie by construction.
* **Numeric faithfulness** and **forbidden phrases** are `n/a` here, because there is no
  generated answer to check. They belong to a model's prose, not to a JSON payload.

**`--mode agent`** asks `nabiz.agent.NabizAgent` each scenario question and adds those rows.
The agent is constructed as `NabizAgent(Nabiz(ctx), config=LlmConfig.from_env())` over *this
harness's* tool layer, so `--offline` and the upstream budget still apply to everything it
calls. A `NabizAgent` this harness cannot hand a client to is a **skip**, not a fallback:
letting the agent build its own would ignore `--offline` and make uncapped requests to a
public gateway.

`NabizAgent` answers with or without a model (ADR 5: Azure for Students may have no quota).
With none configured it routes on keywords to a single tool and renders a template, so the
mode still runs and reports what that path actually achieves — every row is labelled
`no model configured — keyword-routed answers`, and the header carries the model, provider
and answer mode of the run. `--require-llm` turns the absence into a skip instead:

```
$ .venv/bin/python eval/run_eval.py --mode agent --offline --require-llm
--mode agent skipped: no LLM configured; set one of LLM_BASE_URL, LLM_MODEL, OPENAI_API_KEY,
AZURE_OPENAI_ENDPOINT, FOUNDRY_LOCAL_ENDPOINT. Drop --require-llm to measure the agent's
no-model path instead — it answers from keyword routing and is scored as such
Deterministic mode still measures the data layer; the agent-only rows stay n/a until an agent runs.
```

Scoring is split rather than collapsed into one verdict, because "the agent failed" is not a
useful sentence. **Task success** is: it answered, it called every tool the scenario expects,
and every required field was in the payloads it got. Hedging, unsupported numbers and refusal
wording are separate rows, so a run tells you *which* of them broke. "Clean answers" is the
conjunction of all four.

## The scenarios

`journeys.jsonl` holds 24 scenarios — the four journeys of PLAN.md §1 (J1 parking, J2 bus
arrivals, J3 metro status and accessibility, J4 air quality), six each, twelve Turkish and
twelve English. Every place, line and stop is real: 500T is the Tuzla Şifa Mahallesi ↔ 4.
Levent Metro line, 3068 is the İSPARK lot at 15 Temmuz Şehitler Meydanı, 220641 is the
Kavacık Köprüsü stop the 500T actually calls at.

| Key | Meaning |
|---|---|
| `id`, `lang`, `journey` | `j2-en-1`, `tr`/`en`, `J1`–`J4` |
| `question` | what a person would type, in that language |
| `expected_tools` | the tool chain the answer requires, in order |
| `calls` | the same chain with concrete arguments, so the deterministic runner never has to guess them; a call may carry `"expect": "refusal"` and `error_contains` |
| `expected_fields` | field assertions (grammar below) |
| `forbidden_phrases` | overclaiming the answer must not contain |
| `answer_must_contain_any` | agent mode only: the answer must contain at least one of these, so a refusal or a stated limit has to survive into the prose; ignored by the deterministic runner |
| `notes` | why the scenario exists and what the honest answer looks like |

### Field assertion grammar

Paths address the `ToolResult` envelope, so `provenance` and the envelope `note` are
assertable next to the payload:

| Form | Meaning |
|---|---|
| `tool.data.a.b` | present and not null |
| `tool.data.list[].field` | the list is non-empty **and every** element has the field |
| `tool.data.list[?].field` | the list is non-empty and **at least one** element has it |
| `?tool.data.field` | optional: recorded as present or `n/a`, never counted as a failure |
| `tool.data.field == 0` | equality against a JSON literal (`false`, `"low"`, `24`) |

The `?` marker is what keeps the headline number meaningful. Some fields are legitimately
absent: the recorded bus positions age past the ETA engine's 600-second freshness window,
so an offline run returns zero arrivals; an air-quality station publishes a null PM10 hour
now and then. Scoring the weather as a defect would turn the score into noise, so those
checks are reported separately as "optional checks not applicable".

### The two kinds of scenario that must *not* produce an answer

* **Refusal** (`j2-tr-2`, `j2-en-2`): "500T Kadıköy'e ne zaman gelir?" The 500T does not
  serve Kadıköy. The correct behaviour is to refuse and name the lines that do serve the
  stop; an invented minute here is the most expensive error the system can make. The
  harness passes the scenario only if the tool raises with `uğramıyor` in the message. In
  agent mode the refusal also has to survive into the prose, but that is scored on its own
  row — **Refusal / limit stated in the answer** — and in **Clean answers**, not inside task
  success: an agent that gets the refusal from the tool and then writes a minute anyway is
  counted as a task success with a `marker_ok: false` and a stated reason in the JSON. Read
  those two rows together, never the task-success row alone.
* **Honest limits** (`j1-en-2`, `j4-en-2`): typical occupancy with no history yet must
  return `available: false` with the reason, and a 24-hour air-quality outlook must report
  `baseline_only: true` with every point at `confidence: "low"` — it is yesterday's value
  at the same hour, not a forecast in the meteorological sense.

## What each metric means

| Metric | Definition |
|---|---|
| Task success rate | share of scenarios where every call returned (or refused exactly where it should) **and** every required field was present |
| Tool success rate | share of individual tool calls that did not error |
| Required fields present | share of non-optional field assertions satisfied |
| Provenance present | share of calls that returned data carrying a `provenance` stamp |
| Upstream timestamp present | of those, how many carry `reported_at` — the moment **İBB** stamped the data, as opposed to the moment we read it |
| Data freshness | median and p95 of `provenance.reported_at` age, split per source in the report |
| p50 / p95 latency | per scenario (sum of its calls) and per tool, nearest-rank percentiles |
| Error taxonomy | `bad_request`, `upstream_unavailable`, `rate_limited`, `upstream_budget`, `timeout`, `internal:*`, plus `refused_as_expected` and the two inverted cases — `missing_refusal` (the tool answered where the scenario required a refusal) and `wrong_refusal` (it refused, but not for the stated reason) |
| Number-plate leaks | occurrences of a `plaka`/`plate` key or of the İETT plate shape (`34 HO 1000`) in any serialised result; the contract is zero (NOTICE.md) |
| Numeric faithfulness | agent mode: share of the free-standing numbers in the answer that appear in a tool result or in the question |
| Tool-call accuracy | agent mode: called chain vs. `expected_tools`, reported twice — the exact ordered chain, and the looser "every expected tool was called somewhere" |
| Refusal / limit stated in the answer | agent mode: share of the scenarios carrying `answer_must_contain_any` whose prose actually says it |
| Agent's own faithfulness guard agreed | agent mode: how often `NabizAgent`'s internal check reached the same verdict as this harness. Disagreement is the interesting cell: it means one of the two checkers is wrong, and the JSON says which answer |
| Clean answers | agent mode: passed **and** no hedge **and** no unsupported number **and** the refusal stated |
| Forbidden-phrase violations | agent mode: `kesinlikle`, `garanti`, `resmi`, `guaranteed`, `official`, … |
| Tokens / cost | agent mode, only when the provider reports usage |

Four details worth knowing before quoting a number:

* **Percentiles are nearest-rank** and some samples are tiny. A "p95" over three calls is
  the slowest of the three. With 24 scenarios, p95 is the second-slowest — so a single
  cold-start outlier (the first `iett_stops_search` pays ~0.3 s to load the GTFS stop
  index — 264 ms offline, 313 ms in the live run of 8 September 2026, against 0–3 ms for
  every warm call) shows up in the scenario table but not in the p95 cell.
* **Only free-standing numbers are claims.** A digit glued to a letter is a name in this
  domain — `PM10`, `SO2`, `M4`, `500T`, `4.Levent` — and so are timestamps, dates, clock
  times and the `CC BY 4.0` in the attribution line. They are masked before the answer is
  read; checking them produced violations that meant nothing and hid the real ones.
* **An ambiguous number is given every reading.** `1.250` is one thousand two hundred fifty
  in Turkish and one-and-a-quarter in English, and the no-model path answers in Turkish
  whatever language the question was asked in — so a token counts as unsupported only when
  *neither* reading appears in the evidence. Trusting the scenario's language instead
  reported the fallback's Turkish coordinates (`41,0422`) as invented four-hundred-thousands.
* **Forbidden-phrase matching is negation-aware.** "Bu resmi İETT bilgisi değildir" is the
  disclaimer we *want*; a hit followed within 45 characters by a negation marker is not
  counted as overclaiming. Only the bare claim counts.

## Being a polite guest on someone else's gateway

`api.ibb.gov.tr` starts returning 503 to *every* İBB service after roughly fifteen rapid
requests, and İETT documents 100 requests per hour. A live eval that fanned out over 24
scenarios would be a small denial of service against a public endpoint, so the harness
counts every real request and stops:

* `--max-upstream N` (default **8**) caps real requests. Past the ceiling the remaining
  scenarios are recorded as `skipped: upstream budget spent` and excluded from every
  denominator, rather than being silently counted as failures. A scenario that runs *into*
  the ceiling between two of its own calls is abandoned the same way — the ceiling is our
  politeness, not İBB failing to answer, and letting it score a failure would mean the
  number chosen on the command line could move the headline result.
* `--offline` serves the recorded fixtures in `tests/fixtures/` and makes no network call
  at all; the count in the report header is then `0`.
* `--only j2,j3-en` and `--limit N` narrow the selection. Scenarios run in file order and
  share one cache, so a live selection that reuses the same source costs one request no
  matter how many scenarios read it.

A live run therefore covers a **subset** of the 24 scenarios by design. The report header
always states which mode, how many scenarios ran, how many were skipped and how many
upstream requests were spent. For scale: the live run of 8 September 2026
(`results/20260908T082353Z-deterministic-live.md`) covered 13 of the 24 scenarios — all of
J1 and J2, one of J3 — in **8** upstream requests and 42.7 seconds of wall clock, most of
that the client waiting out its own six-second spacing (p95 scenario latency 17.7 s against
tens of milliseconds offline: that gap is politeness, not İBB being slow). Scenarios reusing a source
already read cost nothing, which is why 13 fit into 8 requests. J4 was never reached, so
**the air-quality journey has no live number yet** — run `--only j4` on its own budget when
that matters, rather than raising the ceiling.

The skip is visible rather than silent:

```
`mode=deterministic` · `live` · 1/2 scenarios run, 1 skipped · upstream requests to İBB: 1
| `j3-en-1` | en | J3 | skipped | 0 ms | skipped: upstream budget of 1 requests spent |
```

## ETA accuracy cannot be measured yet — and why

The README's **Bus ETA mean absolute error** row is `n/a`, and it will stay `n/a` for
several days. This is not a missing feature; it is arithmetic. Measuring the error of an
arrival prediction requires pairs of *(what we predicted, when the bus actually arrived)*,
and İETT publishes neither historical predictions nor arrival events. Both halves of every
pair have to be observed by this project, in real time, over days:

1. **Prediction.** Every estimate `iett_next_arrivals` produces is written to `eta_log`
   with its method (`stop_sequence`, `distance`, `schedule`), the target stop, the door
   number, the predicted minutes and the timestamp of the position it was derived from.
2. **Observation.** The collector polls the fleet every two minutes. A vehicle is recorded
   as having arrived when that door number reports the target stop as its `yakinDurakKodu`
   (or comes within a small radius of the stop coordinates when the claim is not credible).
   The first such observation after the prediction is the actual arrival time.
3. **Pairing.** `actual_minutes = arrival − predicted_at`. The error is
   `predicted_minutes − actual_minutes`. A prediction whose bus never appears at the stop
   within a generous window is recorded as *unresolved*, not silently dropped — dropping
   them would flatter the number by discarding exactly the cases the model got wrong.
4. **Reporting.** MAE and median error over all resolved pairs, broken down by method and
   by how many stops away the bus was, with **n** always printed beside the value. PLAN.md
   §8 sets the bar at ≥ 200 resolved arrivals before the number goes in the README, which
   is roughly four to five days of collection.

Until then the honest report is the count of pairs (zero) and the reason, which is what the
harness prints. The same log is what will justify moving the constants in `EtaParams`, and
what a trained model would eventually have to beat.

## Files

```
eval/
├── journeys.jsonl   24 scenarios, 12 TR / 12 EN, six per journey
├── run_eval.py      the harness: runner, metrics, markdown report, --selftest
└── results/         <timestamp>-<mode>-<offline|live>.{json,md} + latest.md
```

Contains public sector information from the İstanbul Metropolitan Municipality Open Data
Portal, licensed under the İBB Open Data Licence (CC BY 4.0).
