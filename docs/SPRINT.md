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

---

## How to read this

| Mark | Meaning |
|---|---|
| **Lane** | Delegated to a lane session working under `AGENTS.md`: it edits only the files its brief names, runs no git write, and hands over suggested commits. The owner reviews the diff and commits it under his own name. |
| **Owner** | Only the owner can do it: it needs his accounts or his machine, spends money or the shared İBB budget (`make` targets marked NETWORK), rewrites history, or is one of the [decisions only the owner can make](#decisions-only-the-owner-can-make). |

Every exit criterion is a check someone else can run: a command and its expected output, a URL, a green CI
run, or a number with the file it comes from. A day is closed when its exit criteria hold, not when its tasks
are ticked. Anything not run is written as `not run: <reason>`.

**Daily rhythm.** Lanes start from a brief with an explicit file list. In the evening the owner reads each
diff and handoff, commits by explicit path, pushes, and watches the CI run. If `main` is red, the next day
starts with the fix and nothing else (AGENTS.md §1, "stop the line"). A number that moved is updated in
PLAN.md §0 in the same commit that moved it.

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
| Journey scenarios | 24 | `eval/journeys.jsonl` |
| Repository security settings | secret scanning and push protection on; Dependabot alerts off; private vulnerability reporting off; `main` unprotected | [`ENGINEERING.md`](ENGINEERING.md) §1 |

---

## The week at a glance

| Day | Date | Goal | Closed when |
|---|---|---|---|
| D0 | Tue 22 Sep | Find out what is exposed; stop making it worse | done |
| D1 | Wed 23 Sep | Land the parallel lanes; first green CI | a `success` CI run on `main` |
| D2 | Thu 24 Sep | Azure reachable and budgeted, nothing billed yet | the Azure probe passes; two budgets exist |
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
| 11 | GitHub settings, minutes each: keep the e-mail address private and block command-line pushes that expose it; two-factor authentication; private vulnerability reporting; Dependabot alerts on, version-update PRs off. After the first green run: a ruleset on `main` that requires the CI check | Owner |
| 12 | Ask the mentor for the written brief: deadline, video length and language, upload channel, whether the repository must be public | Owner |

Status when the lanes finished (23 Sep): tasks 1–9 are done in the shared working tree and were checked
together by the integration pass (lint, the full suite, guardrails, the MCP smoke test and `make ci-local` on
a clean copy). Tasks 10–12 are the owner's.

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

**Goal:** every precondition of `azd up` checked, with a budget in place before anything can spend.

| # | Task | Who |
|---|---|---|
| 1 | Install and sign in: `brew install azure-cli azd`, `az login`, `azd auth login` ([`deploy.md`](deploy.md) §2) | Owner |
| 2 | Register the resource providers (the loop in [`deploy.md`](deploy.md) §2) | Owner |
| 3 | Region gate ([`deploy.md`](deploy.md) §3); record the result with `azd env set AZURE_LOCATION <region>` | Owner |
| 4 | Two budgets with alerts, $20 and $40, in Cost Management — before the first provision ([`deploy.md`](deploy.md) §7) | Owner |
| 5 | `./.venv/bin/python scripts/probe_day0.py --azure --no-network`. `--no-network` because the İBB checks would spend the budget the collector owns. The report is redacted since 23 Sep (task 10: subscription name and state only, tool versions without install paths or build triples), so review the diff of `docs/day0_report.json` before committing it rather than skipping it | Owner |
| 6 | Decide whether to rewrite the 19 commits (see [decisions](#decisions-only-the-owner-can-make)); every day adds more commit ids quoted in docs | Owner |
| 7 | Remove the two harvested worktrees once their content is on `main` | Owner |
| 8 | Add `uv.lock` ([`ENGINEERING.md`](ENGINEERING.md) CD-2). The `mcp` pin is done (`mcp>=2.2,<3`, 23 Sep); the lockfile is not, and CI has to install from it once it exists | Lane |
| 9 | The GTFS decision for the image: without the export `/healthz` reports `gtfs: false` and the ETA tools report missing reference data. `docs/deploy.md` §4.3, §4.4 and the §8 job commands were written on 23 Sep | Lane |
| 10 | `scripts/probe_day0.py` writes `--azure` results redacted. **Done 23 Sep**: the report keeps the subscription's name and state, not its ids or the signed-in account, and home paths become `~` | Lane |
| 11 | Commit `scripts/eta_holdout.py`, the replay proposed in `eval/results/eta.md`. **Done 23 Sep** (`make eta-holdout`); it reads the gitignored lake, so a clone still cannot re-run it | Lane |

**Exit criteria**

- `az account show --query state -o tsv` prints `Enabled`; `azd version` succeeds.
- The probe from task 5 exits 0, or each FAIL row is written down in DECISIONS.md as a gate with its fallback.
- Cost Management lists two budgets, $20 and $40, each with an alert recipient.
- The latest CI run on `main` is still `success`.
- `git worktree list` prints one line.

**Main risk:** the student subscription's allowed-locations policy leaves no region that also offers
Container Apps. **Fallback:** the intersection procedure in [`deploy.md`](deploy.md) §3; if nothing fits, the
laptop collector keeps running under its supervisor, the MCP server is demonstrated over stdio, deployment
moves to after delivery, and the README says "not deployed" in plain words.

---

## D3 — Friday 25 September — deploy; the cloud collects, the laptop stops

**Goal:** a live MCP URL, the collector running as Container Apps Jobs, and never two collectors at once.

| # | Task | Who |
|---|---|---|
| 1 | `make collect-stop`, **then** `azd up` (provision, remote build in ACR, deploy), **then** `azd provision` again, because the jobs are created only by a provision that runs after the first image exists ([`deploy.md`](deploy.md) §4.1–4.3; the five-jobs exit criterion below holds only after that second provision). The order matters: the Jobs plan 66 İETT requests in their peak hour (`NABIZ_OFFLINE=1 .venv/bin/python -m nabiz.collector.job --plan`), the laptop allows itself 80 per hour (DECISIONS #3), and İETT documents 100 — two collectors together can exceed it. The gap between the two shows as a gap in the series and is accepted | Owner |
| 2 | Optional: create the ADX free cluster and paste the `.add database … ingestors` line the `postprovision` hook prints (`azure.yaml`). Lake-only is a valid state: `kustoUri` may be empty (`infra/modules/collectorjobs.bicep`) | Owner |
| 3 | Write down the deployment — time, image digest, outcome — the first data point for deployment frequency ([`ENGINEERING.md`](ENGINEERING.md) §4) | Owner |
| 4 | KQL for job outcomes and data freshness in `kql/`, and one Application Insights view worth a screenshot | Lane |
| 5 | README "Project status": the rows D3 made true (deployed, Jobs) — facts only; numbers wait for D4 | Lane |

**Exit criteria**

- `curl -fsS "$(azd env get-value SERVICE_MCP_URI)/healthz"` returns HTTP 200 and reports `"gtfs": true`.
- `az containerapp job list -g <resource group> -o table` lists five jobs, `caj-<name>-<token>`
  for `lines`, `city`, `metro`, `traffic` and `airquality` — the names `job.py --plan` prints.
- `az containerapp job execution list -n <job> -g <resource group> -o table` shows no `Failed` execution in the
  first two hours, and the `lines` job (`*/3 * * * *`) shows 20 executions per full hour.
- New blobs in the bronze container within ten minutes of the deploy (`az storage blob list … --auth-mode login
  --num-results 5 -o table`; account and container names from `azd env get-values`).
- `pgrep -f collect_forever.py` prints nothing on the laptop.
- An MCP client connected to the deployed URL lists 15 tools; the screenshot goes to `docs/screenshots/`.

**Main risk:** the jobs fail in the cloud — the GTFS export missing from the image (predictions stop, the
positions are still written, per `job.py`), a role assignment that has not propagated yet, or the gateway
treating Azure egress differently from a home connection (unverified). **Fallback:** pause the cloud schedule
first, using the procedure D2 wrote into [`deploy.md`](deploy.md) §8, and only then restart the laptop with
`make collect-supervise` — never both at once. Fix forward the next morning; D4 then measures the laptop
series and says so.

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
| 6 | Decide what `iett_next_arrivals` serves (see [decisions](#decisions-only-the-owner-can-make)), then implement it so that the logged estimator is the served one — what is measured is what users get. Recorded in DECISIONS.md | Owner decides, Lane builds |
| 7 | Optional: agent-mode eval with a local model (`make eval EVAL_ARGS='--mode agent'` with `NABIZ_LLM_BASE_URL` and `NABIZ_LLM_MODEL` set, `src/nabiz/agent/llm.py`). Without it, numeric faithfulness and tool-call accuracy stay `n/a (reason)` | Owner |
| 8 | README Results table refreshed from the new files only | Lane |

**Exit criteria**

- A new `eval/results/<UTC timestamp>-deterministic-live.md` dated 2026-09-26 reports at most 8 upstream
  requests, and `eval/results/latest.md` matches it.
- `eval/results/eta.md` is regenerated: its first line gives resolved and logged counts, and its data window
  reaches past the D3 deployment time.
- `make eval` passes every scenario offline.
- `scripts/guardrails.py` reports `no-fabricated-metrics` PASS.

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
| 1 | README: verify the status table against reality, the Limitations against the D4 ETA finding, and the Turkish section against the English. Done in the working tree on 23 Sep: the real CI badge (no `pending` placeholder left), Container Apps Jobs in the mermaid and in `docs/architecture.svg`, the SVG labelled as the target with the laptop collector as today's | Lane |
| 2 | `docs/video_script.md` rewritten to the D4 numbers; PLAN.md §2's `[T] [S] [E]` filled only from `eval/results/` | Lane |
| 3 | `docs/positioning.md` drift: verify it against the D4 numbers. Fixed in the working tree on 23 Sep: the cost is an estimate (1.20–2.30 USD/week) everywhere including the English pitch, the tool and test counts, the Delta claims, the `uvx` wording and the uncited prices | Lane |
| 4 | Record the video — 2:30 (PLAN.md §14) unless the brief says otherwise; send one `/healthz` request first so the recording does not start on a cold container | Owner |
| 5 | Screenshots: an Application Insights trace, an MCP client on the deployed URL, the web UI at phone width | Owner |

**Exit criteria**

- The video exists and is no longer than the brief allows (2:30 if the brief is silent).
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
**Fallback:** rehearse offline; spend live İETT questions only on the takes that are recorded.

---

## D6 — Monday 28 September — freeze

**Goal:** nothing new; everything that exists is verifiably what the README says.

No new feature, tool, source or dependency. Allowed: a fix that turns a gate green, docs, a video re-take.
A scope cut is recorded in DECISIONS.md (charter §5.4).

| # | Task | Who |
|---|---|---|
| 1 | The whole gate list in one command: `make ci-local` (added on D1; lint, test, smoke, guardrails, authorship) | Lane |
| 2 | Fresh-clone check in a scratch directory: clone, `make venv install test`, with no `data/reference/gtfs/` | Lane |
| 3 | Re-measure the numbers in [`ENGINEERING.md`](ENGINEERING.md) §1 and §12 and in PLAN.md §0; the DORA proxies now include real deployments | Lane |
| 4 | Cost Management: actual spend against the list-price estimate (≈ 1.20–2.30 USD/week in [`deploy.md`](deploy.md) §7, Jobs variant, list prices, from DECISIONS #10's Jobs arithmetic); the MCP app idles at zero replicas | Owner |
| 5 | Submission dry run: repository visibility, links, video upload per the brief | Owner |
| 6 | Optional: roll back once to the previous Container Apps revision and write down the minutes ([`ENGINEERING.md`](ENGINEERING.md) CD-5) | Owner |

**Exit criteria**

- The freeze commit has a `success` CI run.
- The fresh clone passes `make test` without the GTFS export.
- Spend to date is under the $20 budget; no budget alert has fired.
- Every box in PLAN.md §16 is ticked or marked `n/a (reason)`.

**Main risk:** a late defect invites a "small" feature. **Fallback:** cut it and record the cut. What ships is
what D4 measured.

---

## D7 — Tuesday 29 September — deliver

**Goal:** submit, then leave the system in a state the owner chose on purpose.

| # | Task | Who |
|---|---|---|
| 1 | Submit as the written brief says | Owner |
| 2 | Post-delivery state: keep the jobs collecting (history grows, spending continues) or pause them ([`deploy.md`](deploy.md) §8). Bronze keeps 30 days (`bronzeRetentionDays` in `infra/main.bicep`), so without an ADX cluster older history ages out. `azd down --force --purge` deletes the lake — copy the bronze container out first | Owner |
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

## Decisions only the owner can make

| Decision | Latest by | If undecided | Why it is the owner's |
|---|---|---|---|
| Rewrite the 19 commits authored with a personal e-mail (a force-push), or leave them | D2 | leave them | History and identity are his. A rewrite changes every commit id: the ids quoted in `eval/results/eta.md`, `docs/NABIZ.md` and `docs/ENGINEERING.md` go stale, it is a one-time exception to "nobody force-pushes" (AGENTS.md §1), and it cannot recall copies made since the first push on 2026-09-08 |
| GitHub settings: private e-mail and push blocking, two-factor authentication, private vulnerability reporting, Dependabot alerts without version-update PRs, a ruleset on `main` | D1 (ruleset after the first green run) | the gaps stay open — [`ENGINEERING.md`](ENGINEERING.md) §12 calls them the fastest movers | account and repository settings |
| Install `az` and `azd` and sign in | D2 | the deploy slips day for day | his Entra account |
| Region | D2 | [`deploy.md`](deploy.md) §3 procedure | subscription policy |
| Budget alerts | D2, before any provision | no provision without them | money |
| `azd up` and every later provision | D3 | nothing deployed | can create billable resources ([`ENGINEERING.md`](ENGINEERING.md) CD-4) |
| ADX free cluster | D3 | lake only; history ages out after 30 days | his account, outside the subscription |
| Stop the laptop collector; later, pause or keep the cloud jobs | D3 · D7 | one collector at a time, always | the shared İETT budget |
| What `iett_next_arrivals` serves: the calibrated profile or the untuned rate | D4 | the untuned 120 s/stop: 10.18 min against 35.82 for the profile on the 523 held-out predictions (`eval/results/eta.md`) | a product claim; recorded in DECISIONS.md |
| LLM path: student credit (Azure OpenAI or Foundry serverless), a local model, or deterministic only | D4 | deterministic; faithfulness stays `n/a (reason)` | spends credit (PLAN.md §9) |
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
