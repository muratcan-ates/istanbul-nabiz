# Sprint D0–D7 · 22–29 September 2026

The calendar for the week that takes İstanbul Nabız from "works on one laptop, CI never green, nothing
deployed" to "deployed on Azure, measured again, recorded, frozen". [`PLAN.md`](../PLAN.md) is the product
plan and its §0 the current status; this file is the day-by-day schedule. The rules for anyone working in the
repository are [`AGENTS.md`](../AGENTS.md); the reasons behind them are [`ENGINEERING.md`](ENGINEERING.md);
the threat model is [`THREAT_MODEL.md`](THREAT_MODEL.md).

Written on D1, 2026-09-23. Times are İstanbul time (UTC+3) unless marked UTC.

**The delivery date is not confirmed.** Nothing in the repository records the programme's deadline or video
brief (PLAN.md, header). This calendar assumes delivery on D7. If the written brief names an earlier date, the
freeze moves forward; the end of D5 is built to be shippable on its own.

Confirmed: not yet (source: none; confirmed on: none). A date changes only here and in PLAN.md's header line,
with a dated line giving the reason in PLAN.md §0.4, in the same commit.

---

## How to read this

| Mark | Meaning |
|---|---|
| **Lane** | Delegated to a lane session working under `AGENTS.md`: it edits only the files its brief names, runs no git write, and hands over suggested commits. The owner reviews the diff and commits it under his own name. |
| **Owner** | Only the owner can do it: it needs his accounts or his machine, spends money or the shared İBB budget (`make` targets marked NETWORK), rewrites history, or is one of the [decisions only the owner can make](#decisions-only-the-owner-can-make). |

Every exit criterion is a check someone else can run: a command and its expected output, a URL, a green CI
run, or a number with the file it comes from. A day is closed when its exit criteria hold, not when its tasks
are ticked. Every day's exit criteria include the evening exit in the daily rhythm below. Anything not run is
written as `not run: <reason>`.

**Daily rhythm.** Lanes start from a brief with an explicit file list (charter §5.2).

- **Waves.** Lanes run in short waves. A lane writes its handoff to a file as it goes, so a usage limit or a
  closed session loses no work. A wave ends when every lane's handoff is saved; the owner, or the Integrator
  when he asks, reviews it and commits it by explicit path before the next wave starts. When agents are
  unavailable, the day switches to Owner tasks. No large lane starts after D5 noon.
- **Morning.** Close or re-date every row of [Decisions only the owner can make](#decisions-only-the-owner-can-make);
  a missed "Latest by" moves the dependent day in this file, explicitly. Copy the open questions from
  yesterday's handoffs into that table, one row each, with a default.
- **Push.** `git rev-parse --show-toplevel && git branch --show-current` (the main clone, `main`); commit by
  explicit path; `make ci-commit` (unless the pre-push hook already runs it); `git push origin HEAD:main`;
  `gh run watch`. A number that moved is updated in PLAN.md §0 in the same commit that moved it.
- **Evening exit, every day.** `git status --short` shows nothing that is neither committed nor parked by
  name, with its reason, in a handoff; `git status -sb` shows nothing ahead of origin; the latest CI run on
  `main` is `success`. If `main` is red, the next day starts with the fix and nothing else (AGENTS.md §1,
  "stop the line").

---

## Baseline on the morning of D1 (2026-09-23)

| What | Value | Source |
|---|---|---|
| CI on `main` | 13 runs from 2026-09-08 to 2026-09-22, **13 failed**; never green | `gh run list --workflow ci.yml --branch main` |
| Why it fails | tests that read the gitignored GTFS export; on 2026-09-13 also two ruff errors | [`ENGINEERING.md`](ENGINEERING.md) §1 |
| Deployments to Azure | 0 | [`ENGINEERING.md`](ENGINEERING.md) §1 |
| MCP tools | 12 on `main`; 15 in the D1 working tree (`plan_journey`, `line_reliability`, `check_alerts` added) | `git show HEAD:src/ibb_mcp/server.py`; `make smoke`, run offline on D1 |
| Commits authored with a personal e-mail | 19 of 21; the other 2 use the noreply address | `git log --format=%ae \| sort \| uniq -c` |
| Collector | laptop, under a supervisor; watched-line snapshots on 4 of the 15 days from 8 to 22 Sep; nothing collected from 2026-09-14 03:48 to 2026-09-22 19:12 UTC | `src/nabiz/collector/job.py` (module docstring); `eval/results/eta.md` |
| Bus ETA error | MAE **12.94 min**, 1,351 of 6,801 predictions resolved, all made at the untuned 120 s/stop; 27.3% within 5 min | `eval/results/eta.md`, generated 2026-09-23 offline |
| Calibrated ETA profile, on stops it was not fitted to | 35.82 min, against 10.18 min for the untuned rate on the same 523 predictions | `eval/results/eta.md`, "Held-out replay" |
| Last live eval | 2026-09-08: 13 of 24 scenarios run, 13 passed, 8 upstream requests | `eval/results/latest.md` |
| Journey scenarios | 24 on `main` that morning (`7cc0fc1`); 30 since `1599c40` | `git show 7cc0fc1:eval/journeys.jsonl \| wc -l` |
| Repository security settings | secret scanning and push protection on; Dependabot alerts off; private vulnerability reporting off; `main` unprotected | [`ENGINEERING.md`](ENGINEERING.md) §1 |

---

## The week at a glance

| Day | Date | Goal | Closed when |
|---|---|---|---|
| D0 | Tue 22 Sep | Find out what is exposed; stop making it worse | done |
| D1 | Wed 23 Sep | Land the parallel lanes; first green CI | a `success` CI run on `main` |
| D2 | Thu 24 Sep | Azure reachable and budgeted, nothing billed yet | the Azure probe passes; three budgets exist |
| D3 | Fri 25 Sep | Deploy: MCP live, collector on Container Apps Jobs, laptop collector stopped | `/healthz` answers 200; job executions succeed |
| D4 | Sat 26 Sep | Measure again, on live data | a dated live eval and a regenerated ETA report in `eval/results/` |
| D5 | Sun 27 Sep | Demo video and README polish | video recorded; every README and video number traces to `eval/results/` |
| D6 | Mon 28 Sep | **Freeze** — fixes and docs only | green CI on the freeze commit; a fresh clone passes |
| D7 | Tue 29 Sep | Deliver | submitted as the written brief says |

---

## D0 — Tuesday 22 September — audit (done)

**Goal:** know what the public repository exposes, and stop adding to it.

| Task | Who | Result |
|---|---|---|
| Audit of identity exposure and of the plan | Owner + Lane | 19 of 21 commits carry a personal e-mail (baseline) |
| Second deep-research brief | Lane | `7cc0fc1`, `docs/research_prompt_v2.md`. The report came back the same evening; it could read only the README, so its stale conclusions are corrected in PLAN.md §0.2 |
| Stop tracking the collector log | Lane | `c68c6ba` (git dates it 2026-09-23 00:04); the log carried local paths |
| Repository-local git identity set to the noreply address | Owner | `git config --local user.email` prints `135648847+muratcan-ates@users.noreply.github.com` |

**Not done on D0:** CI still red; `c68c6ba` not pushed (`git status -sb` shows `ahead 1`).

---

## D1 — Wednesday 23 September — land the lanes, turn CI green (today)

**Goal:** every change started today either lands reviewed and green, or waits in the open. `main` goes
green for the first time.

The lanes share one working tree, so per-file ownership is the only isolation (AGENTS.md §1).

| # | Task | Who |
|---|---|---|
| 1 | Finish and register three MCP tools: `plan_journey`, `line_reliability`, `check_alerts`, with contract tests and a proposed scenario file | Lane |
| 2 | Harvest the `feat/route-advisor` worktree (13 Sep, uncommitted): route advisor, metro graph, line metadata, traffic profile. **Done 23 Sep** in the working tree; outcome per file in [`route-advisor.md`](route-advisor.md) §9 | Lane |
| 3 | Harvest the `feat/ops-hardening` worktree (13 Sep, uncommitted): Dockerfile, HTTP hardening and `/healthz`, OpenTelemetry, KQL. **Done 23 Sep** in the working tree: code in DECISIONS #15–#16, image and KQL in #10–#11 | Lane |
| 4 | Scrub personal data and real number plates from tracked files and recorded fixtures (guardrails `no-personal-data`, `fixture-plates-synthetic`) | Lane |
| 5 | Fix CI: offline tests read a committed GTFS subset (`tests/fixtures/gtfs_mini/`), so the runner needs nothing gitignored | Lane |
| 6 | Rules: `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json` (attribution off), `SECURITY.md`, `CONTRIBUTING.md`, `docs/ENGINEERING.md`, `scripts/guardrails.py`, `scripts/check_authorship.py` | Lane |
| 7 | Threat model: `docs/THREAT_MODEL.md` | Lane |
| 8 | Collector as scheduled Container Apps Jobs: `src/nabiz/collector/job.py`, `src/nabiz/collector/eta_log.py`, `infra/modules/collectorjobs.bicep`, `infra/modules/collectoridentity.bicep`, and its ADR (DECISIONS #10) | Lane |
| 9 | This calendar and the PLAN.md status refresh | Lane |
| 10 | Read every lane's diff and handoff; commit in the suggested order, staging explicit paths; push; watch the run | Owner |
| 11 | GitHub settings, minutes each: keep the e-mail address private and block command-line pushes that expose it; two-factor authentication; private vulnerability reporting; Dependabot alerts on, version-update PRs off. A ruleset on `main` in two stages. Stage 1: restrict deletions and block force pushes, added after the D2 history-rewrite decision (or lifted for that one push, and the push recorded in PLAN.md §0). Stage 2, requiring the CI check, comes only with a pull-request flow rehearsed once before D5, never during the D6 freeze: a required check refuses direct pushes. Until then the gate is `make ci-commit` before the push, or the pre-push hook, and `gh run watch` after it | Owner |
| 12 | Ask the mentor for the written brief: the deadline (date, time and time zone); the evaluation criteria or rubric; the submission form and its required fields; the video spec (maximum length, language, subtitles, file format, upload channel); whether a deployed URL is required or a local demo is accepted; whether the repository must be public; any sample or reference submission; any product the entry will be compared with | Owner |
| 13 | Rules for code shape and cost, each with a gate: import layers and size ratchets (`scripts/check_architecture.py`), upstream-call and work-once budgets (`tests/test_performance_budgets.py`), the page budget (`scripts/check_web_budget.py`); the alert engine and tracing move into `ibb_mcp` (DECISIONS #19); arrivals serve the untuned rate (DECISIONS #18) | Lane |
| 14 | Web redesign ("Nabız çizgisi", [`design/DESIGN.md`](design/DESIGN.md)): steps 0–2 of its plan, the before measurements and screenshots, the budget gate, and `app.js` split into ES modules with no visible change | Lane |
| 15 | Install `az` and `azd` tonight if possible, so D2 starts at sign-in | Owner |

Status at 16:44 UTC on 23 Sep, from `git log`, `make status` and read-only `gh api` calls:

- **First wave, tasks 1 to 9: landed.** The integration pass checked them together (lint, the full suite,
  guardrails, the MCP smoke test and `make ci-local` on a clean copy); the owner committed and pushed them the
  same night, 31 commits after `c68c6ba`, ending at `d59b5a8`. **The first exit criterion holds**: the run
  for `1599c40` was the first `success` on `main` (2026-09-23 00:40 UTC), and `d59b5a8` is green too.
- **Second wave, tasks 13 and 14: landed** as nine commits, `bb639fe` to `d1b4c57`, after a second
  integration pass with the same gates plus `make architecture` and `make web-budget`. The run for `d1b4c57`
  is `success`: 1250 passed, 1 skipped, 4 xfailed (`gh run view 35822752371 --log`). `origin/main` is
  `d1b4c57`, and nothing is ahead of it.
- **Third wave: pending commit** in the shared working tree (`make status` at 16:44 UTC), in four lanes
  (rules and charter, process, server, web):
  - the rules and the charter brought to the week as it runs: AGENTS.md §9 ("ask the owner first"), the
    brief and handoff templates, the daily rhythm and the scope rules in this file, the owner's key
    procedure in SECURITY.md, and `main` protection in two stages (task 11);
  - the process targets: `make status`, `make ci-commit`, `make lake-backup`, `make eval-record`, the
    ci-local lock, the pre-push rule (only `main` and tags), `eval/` under lint and the complexity check,
    and the `no-azure-ids` guardrail, with the link check widened to every tracked Markdown file;
  - the server: the 90 s line TTL that fits one hot line in the İETT budget (DECISIONS #3; the strict xfail
    became a passing test, so the suite reports 3 xfailed), offline data dated by its capture, and
    `.env.example` listing every `NABIZ_` name the code reads;
  - the redesign's steps 3 to 6 (font subset and icon sprite, `tokens.css` and the stylesheets, the new
    markup with MapLibre loaded only with the first map, the pen line and the data-age ruler), per the
    status table in [`design/DESIGN.md`](design/DESIGN.md) §12. Steps 7, 8, 10 to 12 and the gzip half of
    step 9 are not in the tree: the budget gate lists each finding they remove as a target that may only
    shrink.

  The gate counts on the integrated tree are the Integrator's to measure (`make ci-local`, then
  `make ci-commit` on each commit before the push): the counts in a lane's handoff were taken while another
  lane was still editing. Once pushed, this bullet is rewritten as "landed", with the commit range and the
  CI run, in the same commit.
- **Owner tasks.** Task 10 is done for the first two waves and open for the third. Task 11 is open: at
  16:44 UTC `gh api` shows no ruleset on `main` (`rules/branches/main` is empty, `protected: false`),
  private vulnerability reporting `false` and Dependabot alerts `404`. Task 12 is open: PLAN.md's delivery
  line names no date. Task 15 is open: `command -v az azd` finds neither.
- **Collector.** The laptop collector has written nothing since 05:55 UTC: `make status` at 16:44 UTC found
  no `collect_forever.py` process (`running: no`). Restarting it spends the shared İETT budget, so it waits
  for the owner; D3 moves collection to Container Apps Jobs either way.

**Exit criteria**

- `gh run list --workflow ci.yml --branch main --limit 1 --json conclusion --jq '.[0].conclusion'` prints
  `success` — the first green run on `main`.
- `NABIZ_OFFLINE=1 .venv/bin/python -m pytest -q` reports 0 failed. A mid-D1 run of the shared tree gave
  684 passed, 1 failed, 6 xfailed; the failure was in `tests/test_collector_job.py`, a file a lane was still
  editing.
- `.venv/bin/ruff check src/ scripts/ tests/` is clean.
- `make smoke` reports `lists 15 tools` (`.github/scripts/mcp_smoke.py`: at least 12, each with a real input
  schema).
- `.venv/bin/python scripts/guardrails.py` reports no FAIL, and
  `.venv/bin/python scripts/check_authorship.py origin/main..HEAD` exits 0 before the push.
- `git status --short` shows nothing a lane changed today that is neither committed nor parked by name, with
  the reason, in that lane's handoff.

**Main risk:** edits collide in the shared tree — `src/ibb_mcp/tools.py` and `server.py` are touched by the
tools lane and by both harvests — and a half-finished change is committed together with a finished one.
**Fallback:** explicit-path staging only; a lane that is not green by the evening is parked, not committed,
and becomes D2's first task. If `main` is still red at the end of D1, D2 starts with the fix and nothing else.

---

## D2 — Thursday 24 September — Azure ready, nothing billed

**Goal:** every precondition of `azd up` checked, with a budget in place before anything can spend; nothing billed yet, unless the owner takes the early smoke deploy.

| # | Task | Who |
|---|---|---|
| 1 | Install and sign in: `brew install azure-cli azd`, `az login`, `azd auth login` ([`deploy.md`](deploy.md) §2) | Owner |
| 2 | Register the resource providers (the loop in [`deploy.md`](deploy.md) §2) | Owner |
| 3 | Region gate ([`deploy.md`](deploy.md) §3); record the result with `azd env set AZURE_LOCATION <region>` | Owner |
| 4 | Three budgets with alerts, $5, $20 and $40, in Cost Management, each with an alert recipient, before the first provision ([`deploy.md`](deploy.md) §7) | Owner |
| 5 | `./.venv/bin/python scripts/probe_day0.py --azure --no-network`. `--no-network` because the İBB checks would spend the budget the collector owns. The report is redacted since 23 Sep (task 10: subscription name and state only, tool versions without install paths or build triples), so review the diff of `docs/day0_report.json` before committing it rather than skipping it | Owner |
| 6 | Decide whether to rewrite the 19 commits (see [decisions](#decisions-only-the-owner-can-make)); every day adds more commit ids quoted in docs | Owner |
| 7 | Remove the two harvested worktrees by the procedure below the table. | Owner |
| 8 | Add `uv.lock` ([`ENGINEERING.md`](ENGINEERING.md) CD-2). The `mcp` pin is done (`mcp>=2.2,<3`, 23 Sep); the lockfile is not, and CI has to install from it once it exists | Lane |
| 9 | The GTFS decision for the image: without the export `/healthz` reports `gtfs: false` and the ETA tools report missing reference data. `docs/deploy.md` §4.3, §4.4 and the §8 job commands were written on 23 Sep | Lane |
| 10 | `scripts/probe_day0.py` writes `--azure` results redacted. **Done 23 Sep**: the report keeps the subscription's name and state, not its ids or the signed-in account, and home paths become `~` | Lane |
| 11 | Commit `scripts/eta_holdout.py`, the replay proposed in `eval/results/eta.md`. **Done 23 Sep** (`make eta-holdout`); it reads the gitignored lake, so a clone still cannot re-run it | Lane |
| 12 | Optional, the early smoke deploy ([decisions](#decisions-only-the-owner-can-make)). Only if tasks 1 to 5 pass and the budgets exist: `azd up`. The first run deploys the MCP server and skips the jobs by design ([`deploy.md`](deploy.md) §4.1). Do not run the second `azd provision` before D3's `make collect-stop`. Check `curl -fsS "$(azd env get-value SERVICE_MCP_URI)/healthz"`; `gtfs` may be `false` until task 9 lands. D3 keeps the collector cut-over and its exit criteria | Owner |
| 13 | `/healthz` says what it serves: `"offline"` on both servers, and on the MCP server `"revision"` from `CONTAINER_APP_REVISION` (none locally); the page shows a "kayıtlı veri" badge beside the disclaimer while its server is offline. Tests in `tests/test_server_security.py` and `tests/test_web.py`, and `make web-budget` passes. It lands before the D3 deploy, so the image carries it | Lane |
| 14 | Freeze the MCP contract before the first S5 or S6 split ([`ENGINEERING.md`](ENGINEERING.md) §13): `.github/scripts/mcp_smoke.py --write-contract` writes `tests/fixtures/mcp_contract.json` (each tool's sorted parameters with type and required flag), `tests/test_mcp_integration.py` compares `build_server().list_tools()` with it in process, and CONTRIBUTING.md says that a deliberate parameter change regenerates it in the same commit | Lane |

**Removing a harvested worktree (task 7, Owner), one at a time.** The two are `../nabiz-advisor` (branch
`feat/route-advisor`) and `../nabiz-ops` (branch `feat/ops-hardening`), both at `401ab4b`, which is on
`main`. Below, `<dir>` and `<branch>` stand for one of them.

1. `git -C <dir> status --porcelain` lists every dirty path.
2. For each path, `git diff --no-index <dir>/<path> <path>` against `main`; for a modified tracked file, also
   `git -C <dir> diff 401ab4b -- <path>`. Record each as taken, superseded, or dropped with a reason.
   [`route-advisor.md`](route-advisor.md) §9 does this for one lane; the ops table, including that lane's own
   handoff document, may be private.
3. Anything with no home on `main` is copied to a private folder outside synced folders.
4. `make guardrails architecture test` confirms the D0 and D1 fixes still hold.
5. `find <dir>/data -maxdepth 2 -type l -ls` lists the symlinks into the main tree (`data/lake`,
   `data/reference/gtfs`); `unlink` each one. Never `rm -r`, never a trailing slash: `data/lake/` with a slash
   names the main tree's lake itself. `git worktree remove` does not follow symlinks.
6. `make collect-status` before step 5 and after step 7.
7. Archive the dirty paths privately (a tar of the porcelain list). Only then `git worktree remove --force <dir>`
   and `git branch -d <branch>`. Never the first line of `git worktree list`.

**Exit criteria**

- `az account show --query state -o tsv` prints `Enabled`; `azd version` succeeds.
- The probe from task 5 exits 0, or each FAIL row is written down in DECISIONS.md as a gate with its fallback.
- Cost Management lists three budgets, $5, $20 and $40, each with an alert recipient.
- `gh api repos/muratcan-ates/istanbul-nabiz/rules/branches/main --jq '.[].type'` lists `deletion` and
  `non_fast_forward` (unless the rewrite push is still pending; then PLAN.md §0 says so).
- `gh api repos/muratcan-ates/istanbul-nabiz/private-vulnerability-reporting --jq .enabled` prints `true`.
- `gh api -i repos/muratcan-ates/istanbul-nabiz/vulnerability-alerts` returns `204`.
- `ls .github/dependabot.yml` finds nothing: alerts, not update PRs.
- PLAN.md's delivery line names a date and its source, or says "asked again on <date>".
- The latest CI run on `main` is still `success`.
- `git worktree list` prints one line.
- `make collect-status` counts did not drop, and the per-file outcome for both lanes is written.

**Main risk:** the student subscription's allowed-locations policy leaves no region that also offers
Container Apps. **Fallback:** the intersection procedure in [`deploy.md`](deploy.md) §3; if nothing fits, the
laptop collector keeps running under its supervisor, the MCP server is demonstrated over stdio, deployment
moves to after delivery, and the README says "not deployed" in plain words.

---

## D3 — Friday 25 September — deploy; the cloud collects, the laptop stops

**Goal:** a live MCP URL, the collector running as Container Apps Jobs, and never two collectors at once.

| # | Task | Who |
|---|---|---|
| 1 | `make lake-backup BACKUP_DIR=<private directory>`, **then** `make collect-stop`, **then** `azd up` (provision, remote build in ACR, deploy), **then** `azd provision` again, because the jobs are created only by a provision that runs after the first image exists ([`deploy.md`](deploy.md) §4.1–4.3; the five-jobs exit criterion below holds only after that second provision). The order matters: the Jobs plan 66 İETT requests in their peak hour (`NABIZ_OFFLINE=1 .venv/bin/python -m nabiz.collector.job --plan`), the laptop allows itself 80 per hour (DECISIONS #3), and İETT documents 100 — two collectors together can exceed it. The gap between the two shows as a gap in the series and is accepted | Owner |
| 2 | Optional: create the ADX free cluster and paste the `.add database … ingestors` line the `postprovision` hook prints (`azure.yaml`). Lake-only is a valid state: `kustoUri` may be empty (`infra/modules/collectorjobs.bicep`) | Owner |
| 3 | Write down the deployment: time, `git rev-parse HEAD`, image digest, outcome, and each deviation from [`deploy.md`](deploy.md) with the commit that fixed it. It is the first data point for deployment frequency ([`ENGINEERING.md`](ENGINEERING.md) §4). | Owner |
| 4 | KQL for job outcomes and data freshness in `kql/`, and one Application Insights view worth a screenshot | Lane |
| 5 | README "Project status": the rows D3 made true (deployed, Jobs) — facts only; numbers wait for D4 | Lane |
| 6 | Update, in the same change as the deploy (D3) and as the freeze (D6): the `Last verified` date in AGENTS.md and the charter, charter §3 and §5.4, and the README status table | Lane |
| 7 | When the jobs start writing: `tests/test_infra.py` asserts that the lifecycle rule's only `prefixMatch` resolves to the bronze container (`bronze/`) and that `bronzeRetentionDays` defaults to 30, without pinning soft delete; DECISIONS.md #10 records that the bronze layout and the `kql/` tables change forward only (a new field, file or table, never a rewrite of written partitions) | Lane |
| 8 | By the end of D4: `scripts/check_architecture.py --against <ref>` fails when the pushed range raises or adds an entry in `scripts/architecture_baseline.json` or in the web budget's `TARGETS_BY_CHECK`, or adds an `xfail` under `tests/`, unless a commit body in the range carries `Raises-ratchet: <file> <reason>`. It runs in CI's authorship job and in the pre-push hook, `tests/test_check_architecture.py` shows each condition red, and AGENTS.md §6 and §8 say so in the same commit | Lane |
| 9 | The journey eval in CI: the offline harness reads the committed `tests/fixtures/gtfs_mini/` (or honours `NABIZ_GTFS_DIR`) instead of the gitignored export; `make ci-commit` shows 30 of 30 on the exact commit; only then a "Journey eval (offline)" step in `.github/workflows/ci.yml` and a matching gate in `.github/scripts/ci_local.sh` | Lane |
| 10 | Before D4's demo tag: every limit in one table in `docs/THREAT_MODEL.md` §6, each value copied from the file its row names, and a `limit` field on each refusal (`caller_budget` for the caller's token bucket, `shared_iett_budget` for the hourly İETT budget, on the MCP server and the web API), with one test each, and the server's instructions say what each value means. A server change reaches the demo only through `azd deploy` and the post-deploy smoke below | Lane |

**Exit criteria**

- `curl -fsS "$(azd env get-value SERVICE_MCP_URI)/healthz"` returns HTTP 200 and reports `"gtfs": true`.
- `curl -fsS "$(azd env get-value SERVICE_MCP_URI)/healthz"` also shows `"offline": false` and the new revision.
- Cold start measured once: leave the app idle past scale-to-zero, then
  `curl -o /dev/null -s -w '%{time_total}\n' "$(azd env get-value SERVICE_MCP_URI)/healthz"`; the value and
  its date go into ENGINEERING.md §1.
- `az containerapp job list -g <resource group> -o table` lists five jobs, `caj-<name>-<token>`
  for `lines`, `city`, `metro`, `traffic` and `airquality` — the names `job.py --plan` prints.
- `az containerapp job execution list -n <job> -g <resource group> -o table` shows no `Failed` execution in the
  first two hours, and the `lines` job (`*/3 * * * *`) shows 20 executions per full hour.
- New blobs in the bronze container within ten minutes of the deploy (`az storage blob list … --auth-mode login
  --num-results 5 -o table`; account and container names from `azd env get-values`).
- `pgrep -f collect_forever.py` prints nothing on the laptop.
- A post-deploy smoke against the deployed URL: `/healthz`, an MCP client's tool list (15 tools) and one cheap
  tool call. It runs after every `azd deploy`. The screenshot of that client goes to `docs/screenshots/`; named
  and checked as the screenshot rule under D5 says.

**Main risk:** the jobs fail in the cloud — the GTFS export missing from the image (predictions stop, the
positions are still written, per `job.py`), a role assignment that has not propagated yet, or the gateway
treating Azure egress differently from a home connection (unverified). **Fallback:** pause the cloud schedule
first, using the procedure D2 wrote into [`deploy.md`](deploy.md) §8, and only then restart the laptop with
`make collect-supervise` — never both at once. Fix forward the next morning; D4 then measures the laptop
series and says so. If the deploy slips, cut features, never D4's `make eval-live` and the ETA regeneration.

---

## D4 — Saturday 26 September — measure again, on live data

**Goal:** fresh, dated numbers behind every row of the README's Results table, and a decision on what the ETA
tool serves.

| # | Task | Who |
|---|---|---|
| 1 | `make eval-live`, once (NETWORK; the harness caps itself at 8 upstream calls — `Makefile`) | Owner |
| 2 | `make eval` offline, with the scenarios the D1 lanes proposed merged into `eval/journeys.jsonl` | Lane |
| 3 | Make `scripts/eta_report.py` read the cloud layout: it reads `NABIZ_LAKE_DIR` (default `data/lake`), while the jobs write gzipped NDJSON under `<source>/year=/month=/day=/hour=/` in blob storage ([`deploy.md`](deploy.md) §8) | Lane |
| 4 | Download the cloud ETA predictions and line snapshots into a local lake (`az storage blob download-batch … --auth-mode login`) | Owner |
| 5 | `NABIZ_OFFLINE=1 .venv/bin/python scripts/eta_report.py --diagnose`, regenerating `eval/results/eta.md`; carry the hand-written sections over, as the file itself asks | Lane |
| 6 | Decide what `iett_next_arrivals` serves (see [decisions](#decisions-only-the-owner-can-make)), then implement it so that the logged estimator is the served one — what is measured is what users get. Recorded in DECISIONS.md. **Built on D1 (23 Sep)** as the table's default: the untuned 120 s/stop, the profile only with `NABIZ_ETA_PROFILE_MODE=calibrated` (DECISIONS #18); the owner can still reverse it with that one setting | Owner decides, Lane builds |
| 7 | Only if the owner chose a local model on D2: resolve its name once (`src/nabiz/agent/llm.py`), then run `make eval-record EVAL_ARGS='--mode agent --require-llm'` once. Without it, numeric faithfulness and tool-call accuracy stay `n/a (reason)`. | Owner |
| 8 | README Results table refreshed from the new files only | Lane |
| 9 | Only if a local model was chosen, and before task 7: the eval header and answer layer count answers by `answer_mode` (for example `agent: llm 18 · deterministic 12 (fallback after a model error)`) and never print the configured model name when no answer carried one; with `--require-llm` any fallback makes the exit status non-zero and the header says `model path not measured: <N> fallbacks`; a stub model that raises is not headed as a model run (`tests/test_eval_harness.py`) | Lane |
| 10 | Warm-up that reaches the recorded server: `scripts/warmup.py --url <base>` sends plain GETs to the web UI's `/api` routes behind the four video questions, with an offline test that the route list matches the questions; `make warmup WARM_URL=` passes it (still NETWORK, owner only); its docstring says it otherwise warms only its own process. `docs/video_script.md` gets the warm-up step: within the shortest cache life (`iett_line` in `src/ibb_mcp/cache.py`) before each take, again after a restart or deploy, and the MCP server warmed by asking the question once in the client being recorded | Lane |
| 11 | `make web-demo`: the web UI for a recording, no reload, fixed port (`WEB_PORT=`, needs the web extra) | Lane |
| 12 | `docs/video_script.md`: the recording-day card in place of "Kayıttan önce", each step with its expected output (collector or jobs status; the demo servers the owner starts; `/healthz` of each server on screen; `lsof` shows only those; warm-up; the full URL); the İBB cost of one take from `tests/test_performance_budgets.py` and `make perf-report`; a "Ters giderse" line under each timed section; the "Süre aşarsa kesilecekler" list at the top, filled after the rehearsal | Lane |
| 13 | The web app switches off FastAPI's `/docs` and `/redoc` (they load scripts the page's CSP does not allow, and nothing uses them), with a test that both return 404; `docs/THREAT_MODEL.md` WEB-1 says so, and AGENTS.md §7 gains the check that a change to the CSP, `SECURITY_HEADERS` or a `<script>` or `<link>` in `index.html` shows no CSP violation at phone width | Lane |
| 14 | Walk J1 to J4 once through the web UI at phone width and note the result in PLAN.md §0. | Lane |
| 15 | Rehearsal, in the evening, on the recording machine: the whole take from `docs/video_script.md` with `NABIZ_OFFLINE=1` for the web UI and `ibb-mcp --offline`, timed against 2:30; the Copilot step with the configuration chosen for the video; live, only the deployed `/healthz`, no live questions. The rehearsal take is recorded; it is also the sample on which the owner approves the title card and the look. Notes: which questions answered, the Turkish phrasing each one needs, and the time. | Owner |
| 16 | Demo freeze: `git tag -a demo-2026-09-26 -m "build recorded in the video"` on the deployed commit, then `git push origin demo-2026-09-26`. No deploy between the tag and the last take. | Owner |

**Exit criteria**

- A new `eval/results/<UTC timestamp>-deterministic-live.md` dated 2026-09-26 reports at most 8 upstream
  requests, and `eval/results/latest.md` matches it.
- `eval/results/eta.md` is regenerated: its first line gives resolved and logged counts, and its data window
  reaches past the D3 deployment time.
- `make eval` passes every scenario offline.
- `scripts/guardrails.py` reports `no-fabricated-metrics` PASS.
- Every row under "Program gereksinimleri" in PLAN.md §16 names its evidence or says what is missing (or the
  brief has not arrived, with the date it was last asked for).
- The rehearsal notes list the offline take, the Copilot step and the live `/healthz` as run, or
  `docs/video_script.md` marks a path `NOT RUN: <reason>`.
- `git rev-parse demo-2026-09-26^{commit}` equals the commit in the deployment record, and
  `gh run list --commit $(git rev-parse demo-2026-09-26^{commit}) --json conclusion --jq '.[0].conclusion'`
  prints `success`.

**Main risk:** too few resolved predictions in a day of cloud data — only 19.9% of predictions have ever
resolved (`eval/results/eta.md`). **Fallback:** publish the count and the window exactly as they are; keep the
laptop-era figure beside it, labelled with its dates; never merge the two series without saying so. If the
gateway 503s during `eval-live`: one retry later, otherwise publish the offline run and write
`not run: gateway 503` for live.

---

## D5 — Sunday 27 September — demo video and README polish

**Goal:** the three things a reviewer sees first — the top of the README, the video, the live URL — say the
same true things.

| # | Task | Who |
|---|---|---|
| 1 | Morning: ask the four questions once, live, through the server that will be recorded, and keep only those that answer. This is also the warm-up. | Owner |
| 2 | README: verify the status table against reality, the Limitations against the D4 ETA finding, and the Turkish section against the English. Done in the working tree on 23 Sep: the real CI badge (no `pending` placeholder left), Container Apps Jobs in the mermaid and in `docs/architecture.svg`, the SVG labelled as the target with the laptop collector as today's | Lane |
| 3 | `docs/video_script.md` rewritten to the D4 numbers; PLAN.md §2's `[T] [S] [E]` filled only from `eval/results/` | Lane |
| 4 | `docs/positioning.md` drift: verify it against the D4 numbers. Fixed in the working tree on 23 Sep: the cost is an estimate (1.20–2.30 USD/week) everywhere including the English pitch, the tool and test counts, the Delta claims, the `uvx` wording and the uncited prices | Lane |
| 5 | Before the first take, add up the `TOOL_COSTS` prices of the planned questions against the per-caller bucket (burst and refill in [`deploy.md`](deploy.md) "Knobs"), and their İETT calls against 80 per hour minus the jobs' calls in that hour. Then record the video, 2:30 (PLAN.md §14) unless the brief says otherwise; send one `/healthz` request first so the recording does not start on a cold container | Owner |
| 6 | Screenshots: an Application Insights trace, an MCP client on the deployed URL, the web UI at phone width; named and checked as the screenshot rule under D5 says | Owner |
| 7 | Draft the submission text from PLAN.md §2 and the README Results; numbers only from `eval/results/`. | Lane |

Deliverables (video renders, the subtitle file, the submission text, screenshots not meant for the repository)
live in one private delivery folder outside the repository and outside synced folders. Each handoff names the
exact path.

One lane owns each surface on D4 and D5: the README, `docs/video_script.md`, `docs/screenshots/`, the
submission text. README edits land one lane at a time.

The web UI is not deployed this sprint (`azure.yaml` has one service, `mcp`); the video says it runs locally.

Record from the main clone while `git diff --stat demo-2026-09-26 -- src/` and `git status --short src/` print
nothing, with no lane running. The web UI runs with `make web-demo`, never `make web`, which reloads when a
file changes. A separate checkout needs its own non-editable install, with `NABIZ_GTFS_DIR` and
`NABIZ_PLACES_CSV` pointing at the main tree's `data/reference/`.

During the recording window no lane runs on the recording machine: no servers, tests, builds or edits, until
the owner says the takes are done. The owner starts the demo servers in his own terminals.

From D5 to D7 no commit is made in the GitHub web editor: it skips the pre-push hook and `make ci-commit`.

**Screenshots.** They are named `<YYYY-MM-DD>-<surface>-<deployed|local|offline>-<deterministic|model>.png`,
and each README caption repeats the mode and the date; a local web UI capture says local. Each one is opened
at full size before it is committed and checked for the data age, the disclaimer, no number plate, correct
Turkish letters, no id, key or e-mail, and nothing from another project.

**Exit criteria**

- The video exists, and its render's duration is measured
  (`ffprobe -v error -show_entries format=duration -of csv=p=0 <file>`, or the editor's readout) and is at
  most 150 s, or the brief's limit.
- Every number said in the video appears in `eval/results/` or in a file shown on screen.
- `grep -n "pending" README.md` finds no placeholder badge, and no "Project status" row says "planned" for
  something that exists.
- `scripts/guardrails.py` reports no FAIL.

**Main risk:** the live demo stalls on camera — a cold start after scaling to zero, or İBB 503s. The cold
start has never been measured: the 17.8 s p95 in the live eval is İBB plus the client's own ≥ 6 s spacing
between upstream calls, not a cold start (`eval/results/latest.md`). **Fallback:** record against `ibb-mcp --offline` and say on
screen that it is recorded data; show the deployed URL and its `/healthz` separately.

**Second risk:** rehearsals hammer the deployed server's İETT tools. The server keeps its own 80 per hour in
process, and with the jobs' 66 the two can pass İETT's documented 100 in one hour — left open by DECISIONS #10.
**Fallback:** rehearse offline; spend live İETT questions only on the takes that are recorded. Each process
keeps its own 80 per hour (`src/ibb_mcp/http.py`), so the local web UI, a local stdio server and the deployed
server each believe they have 80, while the jobs and every take share İETT's documented 100. During a take at
most one process that can call İBB is running; the Copilot shot uses that same server over HTTP, or runs after
the others are stopped.

---

## D6 — Monday 28 September — freeze

**Goal:** nothing new; everything that exists is verifiably what the README says.

No new feature, tool, source or dependency. Allowed: a fix that turns a gate green, docs, a video re-take.
A scope cut is recorded in DECISIONS.md (charter §5.4).

| # | Task | Who |
|---|---|---|
| 1 | The whole gate list in one command: `make ci-local` (lint, tests, smoke, guardrails, architecture, web budget, authorship: the gate list in `.github/scripts/ci_local.sh`), then `make ci-commit` on the freeze commit | Lane |
| 2 | Fresh-clone check in a scratch directory: clone, `make venv install test`, with no `data/reference/gtfs/` | Lane |
| 3 | Re-measure the numbers in [`ENGINEERING.md`](ENGINEERING.md) §1 and §12 and in PLAN.md §0; the DORA proxies now include real deployments | Lane |
| 4 | Cost Management: actual spend against the list-price estimate (≈ 1.20–2.30 USD/week in [`deploy.md`](deploy.md) §7, Jobs variant, list prices, from DECISIONS #10's Jobs arithmetic); the MCP app idles at zero replicas | Owner |
| 5 | Submission dry run: repository visibility, links, the video upload per the brief, and the submission text pasted into the form without sending it | Owner |
| 6 | Optional: roll back once to the previous Container Apps revision and write down the minutes ([`ENGINEERING.md`](ENGINEERING.md) CD-5) | Owner |
| 7 | Update, in the same change as the deploy (D3) and as the freeze (D6): the `Last verified` date in AGENTS.md and the charter, charter §3 and §5.4, and the README status table | Lane |
| 8 | Status-word sweep: the command below the table | Lane |
| 9 | Read the subtitle file and the submission text once for dashes and for the fixed spellings in charter §0. | Lane |
| 10 | Tag the freeze commit: `git tag -a v0.1.0 -m "submitted build"`, then `git push origin v0.1.0`. The README "Project status" and the submission text name the tag. | Owner |

**Status-word sweep.** `grep -nE 'in progress|not on main|not yet pushed|working tree|pending|not run|planned|henüz|hâlâ|TODO|TBD|\[T\]|\[S\]|\[E\]|\[N\]' README.md docs/video_script.md docs/positioning.md docs/mcp-usage.md docs/THREAT_MODEL.md SECURITY.md docs/NABIZ.md`.
Each hit is re-measured, dated, or kept on purpose and listed in the D6 handoff.

**Exit criteria**

- The freeze commit has a `success` CI run.
- The fresh clone passes `make test` without the GTFS export.
- Spend to date is under the $20 budget; no budget alert has fired.
- Every box in PLAN.md §16 is ticked or marked `n/a (reason)`.
- The status-word sweep leaves only dated history lines, or hits the D6 handoff lists as deliberate.
- `gh run list --commit $(git rev-parse v0.1.0^{commit}) --json conclusion --jq '.[0].conclusion'` prints
  `success`.

**Main risk:** a late defect invites a "small" feature. **Fallback:** cut it and record the cut. What ships is
what D4 measured.

---

## D7 — Tuesday 29 September — deliver

**Goal:** submit, then leave the system in a state the owner chose on purpose.

| # | Task | Who |
|---|---|---|
| 1 | Submit as the written brief says | Owner |
| 2 | Post-delivery state: keep the jobs collecting (history grows, spending continues) or pause them ([`deploy.md`](deploy.md) §8). Bronze keeps 30 days (`bronzeRetentionDays` in `infra/main.bicep`), so without an ADX cluster older history ages out. `azd down --force --purge` deletes the lake — copy the bronze container out first. Keep the laptop-era archive from `make lake-backup`: it is the only copy of that history. Write the first "sync bronze by" date (the D3 deploy date plus 30 days) into PLAN.md §0, or record the decision to let cloud history expire. | Owner |
| 3 | Retro in PLAN.md §0: what the week changed, measured. The stretch list (PLAN.md §11, Day 7) opens only after submission | Lane |

**Exit criteria:** the owner holds the submission confirmation (outside the repository); the latest CI run on
`main` is `success`; PLAN.md §0 is dated 2026-09-29.

**Main risk:** the deadline turns out to be earlier than D7. **Fallback:** the end of D5 is shippable by
design; the freeze moves forward to meet the date.

---

## Definition of Done

- **A task:** the checklist in [`AGENTS.md`](../AGENTS.md) §7. [`ENGINEERING.md`](ENGINEERING.md), written on
  D1, gives the reason for each item and the check that enforces it — or says that nothing does yet.
- **A day:** its exit criteria hold when someone other than the lane that did the work runs them.
- **The sprint:** the D6 exit criteria hold on the commit that is submitted.

---

## Scope rules for this week

- **D4 keeps its measurement day.** If D3 slips, features are cut (redesign steps, new tools), never D4's
  `make eval-live` and the ETA regeneration. The cut is recorded in `DECISIONS.md`.
- **The page stops changing after D4.** Redesign steps 3 to 12 land by the end of D4 or are cut and recorded;
  from D5 the page changes only by fixes.
- **A new idea is decided in one line before any lane starts on it:** the PLAN.md §2 outcome it moves, any
  conflict with a hard rule (privacy, the İBB budget, honest numbers, nothing billable), its upstream or credit
  cost, and the decision: in, cut, or after delivery. Cuts go to `DECISIONS.md`.

---

## Decisions only the owner can make

| Decision | Latest by | If undecided | Why it is the owner's |
|---|---|---|---|
| Rewrite the 19 commits authored with a personal e-mail (a force-push), or leave them | D2 | leave them | History and identity are his. A rewrite changes every commit id: the ids quoted in `eval/results/eta.md`, `docs/NABIZ.md` and `docs/ENGINEERING.md` go stale, it is a one-time exception to "nobody force-pushes" (AGENTS.md §1), and it cannot recall copies made since the first push on 2026-09-08. If it happens, run right after the push: every backticked 7 to 40 character hex id in tracked Markdown passes `git cat-file -e <id>^{commit}`, and every cited `DECISIONS #N` exists; update what it reports |
| GitHub settings: private e-mail and push blocking, two-factor authentication, private vulnerability reporting, Dependabot alerts without version-update PRs, optionally CodeQL default setup; a ruleset on `main`, stage 1 (no force push, no deletion), and for stage 2 either (a) a short-lived branch and pull request per evening batch with the jobs 'Lint, test, guardrails and MCP smoke test' and 'Authorship gate' required and no bypass actor, only once private e-mail is on, or (b) direct pushes gated by the pre-push hook running `make ci-commit` | D2 | stage 1 only, and (b) | account and repository settings |
| Concurrent lane sessions | D2 | at most 2 plus the Integrator | his machine, his usage and his review time |
| Install `az` and `azd` and sign in | D2 | the deploy slips day for day | his Entra account |
| Region | D2 | [`deploy.md`](deploy.md) §3 procedure | subscription policy |
| Budget alerts | D2, before any provision | no provision without them | money |
| `azd up` and every later provision | D3 | nothing deployed | can create billable resources ([`ENGINEERING.md`](ENGINEERING.md) CD-4) |
| ADX free cluster | D3 | lake only; history ages out after 30 days | his account, outside the subscription |
| Stop the laptop collector; later, pause or keep the cloud jobs | D3 · D7 | one collector at a time, always | the shared İETT budget |
| What `iett_next_arrivals` serves: the calibrated profile or the untuned rate | D4 | the untuned 120 s/stop: 10.18 min against 35.82 for the profile on the 523 held-out predictions (`eval/results/eta.md`). In effect since 23 Sep (DECISIONS #18) | a product claim; recorded in DECISIONS.md |
| LLM path: deterministic only, or a local model that cannot bill | D2 | deterministic; numeric faithfulness and tool-call accuracy stay `n/a (reason)`, and neither the video nor the README claims a model path | a model path has to be measured before the video, and D4 is the only day for it |
| Early smoke deploy of the MCP server on D2 | D2 16:00 | no; D3 as planned | the container registry bills from D2 (the daily figure in [`deploy.md`](deploy.md) §7) |
| Copilot shot in the video: the deployed URL (the HTTP entry in [`mcp-usage.md`](mcp-usage.md)) or local stdio | D4 rehearsal | whichever answered in the rehearsal | what the video calls live |
| Publish the live URL in the README; minimum replicas on demo day | D5 | URL left out; `minReplicas` 0 | public exposure and cost |
| Record and upload the video | D5 | — | his voice, his account |
| Obtain the written brief and deadline from the mentor | D1 | assume D7 | only he talks to the mentor |
| OIDC federated credential for deploying from CI | after delivery | no; `azd` from the laptop | tenant permission; CD-4 |
| Keep every clone and scratch file out of iCloud-synced folders (Desktop, Documents) | standing | — | his machine; charter §1.2 |

---

## Not in this sprint, and why

The second deep-research report (22 Sep) recommended some of these. PLAN.md §0.2 has the full list of its
corrections.

- **Coding agents that commit or open pull requests from CI** — the Claude Code GitHub Action, the Copilot
  coding agent. Rejected: they appear as contributors, which AGENTS.md §2 forbids, and they need a token secret
  in CI, which is a billing path no workflow here may have.
- **`.github/copilot-instructions.md`, `copilot-setup-steps.yml`.** Not needed: `AGENTS.md` is the single
  entry point, and `CLAUDE.md` imports it rather than copying it.
- **Raising the per-stop rate towards 235 s.** The held-out replay shows the calibrated rates are worse on
  stops they were not fitted to (`eval/results/eta.md`).
- **A new source (EPDK charging stations), Content Safety Prompt Shields.** A new source is a feature and must
  be verified first; Prompt Shields protect a model call that deterministic mode never makes. After delivery.
- **Fabric Eventhouse, Event Hubs, PyPI, Copilot Studio.** The stretch list in PLAN.md §11, after delivery.
- **A new research brief.** PLAN.md §0.2 checked the last report claim by claim; a new one would not land
  before the freeze.
