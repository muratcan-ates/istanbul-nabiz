# scripts/

One-shot developer scripts. None of them are imported by the MCP server or the collector —
they exist to *check* the environment and to *build* the reference data that lives in
`data/reference/` and `tests/fixtures/`.

Everything here talks to `api.ibb.gov.tr`, which 503s after roughly fifteen rapid calls, and
the İETT SOAP service is capped at **100 requests/hour** (documented, PLAN §18). Every script
that goes to the network therefore throttles itself and prints what it is doing. Do not
remove the sleeps.

Run them with the project venv so `httpx` and `ibb_mcp` are importable:

```bash
./.venv/bin/python scripts/<name>.py
```

---

## `probe_day0.py` — the Day-0 gate

Answers one question: *can the seven-day sprint actually start today?* It runs 21 numbered
checks across four sections, prints an aligned PASS/FAIL/SKIP table, writes
`docs/day0_report.json`, and ends with a **NEXT ACTIONS** block that says what to do about
each failure. Exit code is `0` when nothing FAILED — SKIP is fine — and `1` otherwise, so it
works as a CI or pre-flight gate.

| Section | Checks | Network |
|---|---|---|
| `T1`–`T8`  TOOLS | python 3.12, uv, az, azd, func, foundry, git, gh | none |
| `A1`–`A4`  AZURE | subscription/tenant/identity · allowed-regions policy · Functions Flex regions ∩ allowed regions · resource provider registration state | `az`, only with `--azure` |
| `I5`–`I10` İBB | AQ stations · AQ 30-day window · İSPARK lots · İETT 500T positions · Metro service status · traffic index Accept header | api.ibb.gov.tr |
| `G11`–`G13` GTFS | stops.csv/routes.csv present · `yakinDurakKodu` → `stop_code` · `guzergahkodu` → `route_code` | none |

`foundry` and `gh` report SKIP rather than FAIL when missing — they are only needed on the
local-LLM path and for CI secrets. Everything else in TOOLS is a hard gate.

`A4` **reports** provider registration state and never registers anything; registering is a
deliberate act, not a side effect of a probe.

`G12`/`G13` are the load-bearing ones: the ETA engine (PLAN §7) joins a live bus to the GTFS
timetable on `stop_code` — **not** `stop_id`, which matches nothing. If that join ever
breaks, the fallback is nearest-stop-by-haversine and an ETA expressed as "km + min" instead
of "n stops" (PLAN §15).

### Flags

| Flag | Effect |
|---|---|
| *(none)* | tools + İBB + GTFS; 6 İBB calls |
| `--azure` | additionally run `A1`–`A4`; requires `az login` |
| `--no-network` | skip `I5`–`I10` entirely; instant, safe to re-run as often as you like |
| `--traffic-both` | spend a 7th İBB call fetching the traffic index *without* an `Accept` header, to prove what the header actually changes |
| `--json-only` | print the JSON report on stdout and nothing else |

### Politeness

At most **6** İBB calls per run (7 with `--traffic-both`), at least **6 seconds** apart, with
a live countdown on stderr so a human can tell the script is waiting rather than hung. A
check that would exceed the budget returns SKIP instead of making the call.

### Output

The human table goes to stdout, per-check progress and the countdown go to stderr, so
`probe_day0.py 2>/dev/null` gives a clean report. `docs/day0_report.json` is rewritten on
**every** run, including `--no-network` ones — re-run with the flags you actually care about
if you want the file to reflect a full pass.

### Findings worth knowing (real runs, 2026-09-08)

- All six İBB endpoints answered; 500T carried 33–34 vehicles a minute apart, and the GTFS
  joins came back 31/31 and 2/2.
- A 30-day air-quality window returned **721 hourly rows with no duplicates**, so the
  two-year backfill in PLAN §10 needs no pagination.
- The traffic index endpoint returns a **JSON body labelled `Content-Type:
  application/xml;charset=utf-8`** when asked with `Accept: application/json`. Never
  dispatch on content type for this endpoint — that mislabelling is the real trap, and it
  is the one finding here that is fully established.
- Whether the `Accept` header is still *required* is **not yet settled**. The
  `--traffic-both` run that suggested "no" was made through httpx, which injects
  `Accept: */*` into every request it builds — so that arm proved the server answers
  `*/*` with JSON, not that it answers a *missing* Accept with JSON, and `*/*` is exactly
  the value content negotiation treats as "send me your default". The probe now pops that
  header (`http(..., drop_headers=("accept",))`, verified against a local echo server on
  both transports), but it has not been re-run against İBB since. Until it is, keep
  sending `Accept: application/json` and treat the endpoint as documented.

---

## `capture_fixtures.py` — record real İBB responses

Calls each endpoint once and writes `tests/fixtures/*.json` (plus the raw SOAP envelopes and
a `_capture_report.json` with status codes, byte counts and timings). Those fixtures are what
the contract tests and `Settings(offline=True)` read, so the test suite never touches the
network.

Uses `urllib` only, keeps 7 s between gateway calls, and makes **at most 3 SOAP calls**.
Large lists are trimmed before writing so the fixtures stay reviewable in a diff.

Re-run it when an İBB payload changes shape — `probe_day0.py` tells you when it has, by
comparing live counts against the values recorded on 2026-09-08 (28 AQ stations, 249 İSPARK
lots) and emitting a NEXT ACTIONS line on drift. Do not re-run it casually: it spends part of
the İETT hourly budget.

---

## `build_places.py` — rebuild the gazetteer

Regenerates `data/reference/places.csv`, the lookup table behind the `places_resolve` tool,
from fixtures already on disk: Metro station names, air-quality station names, İSPARK
district centroids, and a short hand-written landmark list for the names people actually say
("Taksim", "Kadıköy İskele"). **No network access** — run `capture_fixtures.py` first if the
fixtures are stale.

Note the explicit Turkish case mapping in that file: `str.title()` mangles the dotted capital
İ into a combining sequence, so casing is done with a translation table.

---

## Order on a fresh machine

```bash
uv venv -p 3.12 .venv && source .venv/bin/activate
./.venv/bin/python scripts/probe_day0.py --no-network   # what is missing locally?
# ... install what NEXT ACTIONS told you to, az login ...
./.venv/bin/python scripts/probe_day0.py --azure        # full gate, 6 İBB calls
./.venv/bin/python scripts/capture_fixtures.py          # only if fixtures are stale
./.venv/bin/python scripts/build_places.py              # rebuild the gazetteer
```
