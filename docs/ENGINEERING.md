# Engineering handbook

How this repository is built, rule by rule. Every rule is tied either to an incident this repository has
already had or to a named reference with a link, and every rule says what enforces it — or that nothing
does yet. [`AGENTS.md`](../AGENTS.md) is the short, binding version for coding agents;
[`docs/NABIZ.md`](NABIZ.md) is the charter. This file is the *why*. How the code is shaped (§13) and how its
cost is budgeted (§14) come last, because they are the newest rules.

Last verified: 2026-09-23, against `main` at `d59b5a8` plus the uncommitted working tree of that day. The CI,
commit, test and size rows of §1 were re-measured after `d59b5a8` was pushed; the others are from that morning.

**Maturity scale** used throughout, the same one used to review the previous project (§11):
`0` absent · `1` ad hoc, not written · `2` written, not enforced · `3` enforced — a failing check stops the
change · `4` enforced and measured over time. "Unknown" means there is no evidence, and nothing is guessed.

**Where numbers live.** Numbers that change week to week appear only in §1 and in the self-assessment
(§12), each with the command that reproduces it. Re-measure before quoting; do not copy them elsewhere.

---

## 0. Principles

1. **A rule without a gate is a wish; a gate that has never been red is not a gate yet.** Each rule below
   names its machine check, or says "none".
2. **Measure or say `n/a (reason)`.** Missing data is not zero, and an in-sample fit is not accuracy.
3. **Red is not normal.** A check that is always red carries no signal: a new failure looks exactly like
   the old one.
4. **A pipeline that has never run is a document.** Grow delivery machinery from real runs.
5. **Cheap standard tools before custom gates** — a secret scanner and a dependency audit before another
   bespoke checker.
6. **Process serves the product.** No record that no gate reads; no gate whose only job is to feed a gate.
7. **Human attention is the scarce resource.** Agents produce more than one person can read, so the system
   points the owner's review at the risky paths, not at everything.

---

## 1. State on 2026-09-23 (measured)

| Fact | Value | Reproduce with |
|---|---|---|
| Commits on `main` | 52, all pushed (21 on the morning of 2026-09-23) | `git rev-list --count HEAD`; `git status -sb` |
| Pull requests ever opened | 0 | `gh api 'repos/muratcan-ates/istanbul-nabiz/pulls?state=all' --jq length` |
| `main` protected / rulesets | `protected: false` / `[]` | `gh api repos/muratcan-ates/istanbul-nabiz/branches/main --jq .protected`; `gh api repos/muratcan-ates/istanbul-nabiz/rulesets` |
| CI runs on `main` | 15: **13 failed**, then **2 succeeded** (`1599c40` and `d59b5a8`, the first green runs), 0 cancelled | `gh run list --workflow ci.yml --branch main --limit 100` |
| Why they fail | 10 runs: the same 3 tests in `tests/test_web.py`, which read GTFS files under the gitignored `data/reference/gtfs/` (176 MB locally), so the runner has none. 3 runs on 2026-09-13: the ruff gate (2 errors), so pytest never ran. Fixed on 2026-09-23 (`tests/fixtures/gtfs_mini`, DECISIONS #17), pushed with `1599c40`, whose run was the first green one | `gh run view <id> --log-failed` |
| First and latest CI run | 2026-09-08 08:49 UTC · 2026-09-23 00:44 UTC. Red from the first run until 2026-09-23 00:40 UTC (`1599c40`), 14.7 days | same |
| CI duration (queued to completed) | median 23 s, range 17–43 s (n = 15; the two green runs 41 and 43 s, because pytest now runs) | `createdAt`/`updatedAt` from `gh run list --json` |
| Local test suite | 1250 passed, 1 skipped, 4 xfailed on the working tree with the review fixes, and the same on the clean copy `make ci-local` builds (2026-09-23; 1214 after the second integration pass, 943 at `d59b5a8`). The fourth xfail was the İETT hourly budget (OPT-3); it became a passing test when the line TTL went to 90 s later that day | `NABIZ_OFFLINE=1 .venv/bin/python -m pytest -q` |
| `scripts/guardrails.py` | 12 checks, 0 failed, 1 warning on the working tree (the warning is a truncated local file the loader never reads), 0 warnings on the clean copy; a blocking CI step since `1599c40` | `NABIZ_OFFLINE=1 .venv/bin/python scripts/guardrails.py` |
| Deployments | 0 | `gh api repos/muratcan-ates/istanbul-nabiz/deployments --jq length` |
| Secret scanning / push protection | enabled / enabled | `gh api repos/muratcan-ates/istanbul-nabiz --jq .security_and_analysis` |
| Dependabot alerts · security updates | off (HTTP 404) · disabled | `gh api -i repos/muratcan-ates/istanbul-nabiz/vulnerability-alerts` |
| Private vulnerability reporting | disabled | `gh api repos/muratcan-ates/istanbul-nabiz/private-vulnerability-reporting` |
| Commit identity | 33 of 52 commits use the noreply address, the other 19 are the early ones with a personal address; 0 carry a co-author trailer or an assistant footer (the `grep` finds 1 line: prose in the body of the commit that adds the authorship gate) | `git log --format='%ae'`; `git log --format=%B \| grep -ciE '^co-author\|generated (with\|by)'` |
| Lane branches from 2026-09-13 | `feat/route-advisor`, `feat/ops-hardening`: 0 commits past `401ab4b`, their work uncommitted in two worktrees; `main` is 5 commits ahead. Both harvested into the working tree on 2026-09-23 (outcome per file in `docs/route-advisor.md` §9, DECISIONS #11, #15, #16); the worktrees can go once that lands | `git worktree list`; `git rev-list --count 401ab4b..main` |
| Markdown vs product code (tracked at `d59b5a8`) | 7,914 lines of Markdown; 17,242 lines of Python under `src/` (5,059 and 12,647 at `c68c6ba`; the working tree adds to both) | `git grep -h -c '' HEAD -- '*.md' \| awk '{s+=$1} END {print s}'`; the same with `'src/*.py'` |

The single most important line in that table is the fourth. It is the failure the previous project was
reviewed for (§11), repeated here in smaller form until the first green run on 2026-09-23.

---

## 2. Continuous integration

Reference: Martin Fowler, *Continuous Integration* —
<https://martinfowler.com/articles/continuousIntegration.html> ("every push to mainline should trigger a
build", "fix broken builds immediately", "keep the build fast", "make the build self-testing").

| # | Rule | Why (incident or reference) | Enforced by | State |
|---|---|---|---|---|
| CI-1 | Every push to `main` and every pull request runs CI; the pipeline is code in the repo. | Fowler | `.github/workflows/ci.yml` | holds |
| CI-2 | Local equals CI: one command runs the gate list CI runs. | "It passed locally" is only useful if locally means the same checks | `make ci-local` checks the working tree, untracked files included; `make ci-commit` checks the commit a push would publish | holds locally (green on a clean copy, 2026-09-23) |
| CI-3 | **Stop the line.** While `main` is red, the only change that merges is the fix. No "this check may stay red". | §1: the first 13 runs were red, for 14.7 days, until `1599c40`. Two lint errors landed on 2026-09-13 and failed three runs before pytest could start, looking exactly like the failure already there — red hid a new defect. The previous project's red `main` silently switched its delivery off (§11) | stage 1 (no force push, no deletion) now; the required CI check only with a rehearsed pull-request flow. Until then: `make ci-commit` before the push (or the pre-push hook) and `gh run watch` after it | **green since `1599c40`, not gated**: nothing stops a red change from landing until the ruleset exists |
| CI-4 | **Hermetic tests.** CI must not need a file that exists only on a laptop. | The three failing tests read `data/reference/gtfs/`, which is gitignored. They pass locally and fail on every runner — a dev/prod parity failure (Twelve-Factor X) | `tests/fixtures/gtfs_mini` behind the shared test settings; `make ci-local` checks the working tree, untracked files included; `make ci-commit` checks the commit a push would publish | holds: pushed with `1599c40`, green on the runner |
| CI-5 | Keep the build fast; never cancel a run on `main`. | Fowler. The previous project cancelled a large share of its `main` runs through `cancel-in-progress` | `ci.yml`: `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}` | holds (on `main` since `1599c40`) |
| CI-6 | A gate proves it can fail. A new check lands with evidence that it goes red on the incident it guards. | Fowler, "self-testing"; `scripts/guardrails.py` is built as regression tests for real incidents | review | partial |

CI-3 and CI-4 are one piece of work: every offline test reads a small committed GTFS subset under
`tests/fixtures/` instead of `data/reference/gtfs/`; once that is green on a runner, protect `main`. The
subset exists in the working tree (2026-09-23); what remains is the push, the first green run and the
ruleset.

## 3. Continuous delivery and trunk-based development

References: Humble & Farley, *Continuous Delivery* — <https://continuousdelivery.com/>; trunk-based
development — <https://trunkbaseddevelopment.com/> and DORA's capability page
<https://dora.dev/capabilities/trunk-based-development/>.

| # | Rule | Why | Enforced by | State |
|---|---|---|---|---|
| CD-1 | **Deploy for real before writing more delivery automation.** First `azd up`, then one workflow. | The previous project wrote deploy, release and rollback workflows that never ran once (§11) | review | holds — CI only compiles Bicep; deployment is `azd` from a laptop until OIDC works (`.github/workflows/README.md`) |
| CD-2 | **Build once, from a lock.** The artefact that is tested is the artefact that ships. | Humble & Farley. On `main`, `pyproject.toml` allows `mcp>=1.2` while the code imports the 2.x API (`from mcp.server.mcpserver import MCPServer`); the working tree pins `mcp>=2.2,<3`. There is no lockfile yet | none | **gap**: add `uv.lock` before the first image; build the image from it |
| CD-3 | **Short-lived branches, integrated daily.** A lane that cannot land in a day is split. | DORA trunk-based development. §1: two lane worktrees from 2026-09-13 still hold uncommitted work ten days later, five commits behind `main` | SPRINT evening exit (review) | **gap** |
| CD-4 | Deploy credentials are federated (OIDC), never a stored secret; `azd provision` stays manual because it can create billable resources. | GitHub Actions hardening <https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions> | no workflow reads `secrets.*` (`grep -rn 'secrets\.' .github/`) | holds |
| CD-5 | Rollback is rehearsed once, and the minutes are written down, before anyone relies on it. | Humble & Farley; Container Apps keeps revisions | none | not started — nothing is deployed |

## 4. DORA: how we measure, and what it says today

DORA's current model has five delivery metrics — change lead time, deployment frequency, failed deployment
recovery time, change fail rate and deployment rework rate: <https://dora.dev/guides/dora-metrics/>.
All five are defined over **production deployments**, and this project has had none, so all five are
undefined. The proxies below are labelled as proxies; they say something about integration, not delivery.

| Metric | Today | Proxy we can measure | Proxy value (2026-09-23) |
|---|---|---|---|
| Deployment frequency | undefined — 0 deployments | — | — |
| Change lead time | undefined | commit time → first CI run on `main` that contains the commit | median 0.1 min, p90 53.6 min, max 157 min (n = 20 pushed commits) — commits go straight to `main` |
| Change fail rate | undefined | share of `main` CI runs that fail | 13 / 13 |
| Failed deployment recovery time | undefined | time `main` CI stays red | 14.7 days, from the first run to the first green one (`1599c40`) |
| Deployment rework rate | undefined | — | — |

How the proxies were produced, so anyone can redo it:

```bash
gh run list --workflow ci.yml --branch main --limit 200 \
  --json headSha,conclusion,createdAt,updatedAt > runs.json   # conclusions, durations
git log --format='%H %cI' origin/main                          # commit times
# lead-time proxy: for each commit, the first run whose headSha has it as an ancestor
#   (git merge-base --is-ancestor <commit> <headSha>), minus the commit time
```

Rules: the measurement is read-only (`gh` GET calls and `git log`), and a scheduled job may print it but
**never commits it** — a bot committing metrics would put a bot in the contributor list. A missing event is
reported as unavailable, not as 0. Individuals are never ranked. Once `azd deploy` runs, each deployment is
recorded (environment, image digest, time, outcome), and deployment frequency and lead time become real.

## 5. AI-assisted SDLC

The loop, from charter §5: **spec → brief → lane → handoff → Integrator review → eval-gated merge**. The
human owner is accountable for every change and is the author of every commit. Coding agents run locally, in
sessions the owner starts, under the owner's git identity; no hosted agent or bot opens pull requests or
commits here.

| Stage | Artefact | Who | Gate |
|---|---|---|---|
| Spec | charter + research digest | owner, Integrator | charter §2: a fact not in the verified table is re-verified before anyone relies on it |
| Brief | goal, owned files, DoD, out of scope | Integrator | charter §5.2 template |
| Lane | changes to owned files only | one agent per lane | AGENTS.md §1; review |
| Handoff | what changed, commands run with pass/fail counts, what was not run | the lane | charter §5.3 format |
| Integrator review | read the diff, run the gates | owner + Integrator | `make ci-local` |
| Merge | explicit-path commits under the owner's identity | owner | CI on `main`; **the eval is run by hand today** (`make eval`), it is not a CI gate yet |

| # | Rule | Incident or reference | Enforced by |
|---|---|---|---|
| AI-1 | Agent instructions are code: one short `AGENTS.md`, a `CLAUDE.md` that only imports it, dated, pointing to the charter instead of copying it. | Previous project: an `AGENTS.md` that pointed at a long-stale branch (§11); `AGENTS.md` convention <https://agents.md/>; Claude Code imports <https://code.claude.com/docs/en/memory> | guardrail `agent-rules-links`: every repository path and `make` target named in `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md` exists, and every relative link in a tracked Markdown file resolves |
| AI-2 | **One lane, one worktree, one file list.** | On 2026-09-13 two sessions edited one working tree at once. A branch does not isolate that: `git checkout` moves the tree under the other session, and two agents writing one file lose each other's edits with no conflict marker. The ops lane moved to its own worktree for that reason (handoff on the unmerged `feat/ops-hardening`) | review |
| AI-3 | **Lane agents never commit or push; staging is by explicit path.** | Previous project: concurrent sessions' `git add -A` swallowed another lane's work, and a lane's work was left uncommitted in a sandbox | review |
| AI-4 | **No AI attribution; noreply identity.** | Owner's rule, after an assistant appeared in a contributor list on an earlier project | `.claude/settings.json`, `.vscode/settings.json`; `scripts/check_authorship.py` (commits; before a push through `.githooks/pre-push` once `make hooks` has run); guardrail `no-ai-attribution` (files) |
| AI-5 | **A research brief names one subject and one repository, embeds the verified current state, and opens with a proof-of-reading gate.** | Commit `7cc0fc1`: the first brief linked only another project's repo, so the research model planned the wrong project, took a stale README section for current state and reported a 314-commit repository as a 10-commit MVP | review (`docs/research_prompt_v2.md` is the template) |
| AI-6 | **When lanes collide, the first fix is less concurrency, not another gate.** | Previous project: every collision produced a new gate or document, never fewer agents | the lane ceiling in `docs/SPRINT.md` (owner decisions); the lock in `.github/scripts/ci_local.sh`; otherwise review |
| AI-7 | The owner's review goes to risky paths first: `src/ibb_mcp/{http,cache,models,server}.py`, `.github/`, `.githooks/`, `.claude/`, `scripts/guardrails.py`, `infra/`. | Fowler/ISE code review; principle 7 | review |

## 6. Testing strategy and the eval harness

References: the practical test pyramid — <https://martinfowler.com/articles/practical-test-pyramid.html>;
Google SRE on testing for reliability — <https://sre.google/sre-book/table-of-contents/>.

Layers, fastest first: unit tests over recorded fixtures (`tests/`) → the real server
over the wire (`tests/test_mcp_integration.py` spawns `python -m ibb_mcp.server` and talks MCP to it) →
whole-tree regression checks (`scripts/guardrails.py`) → the journey eval (`eval/run_eval.py`, 30 bilingual
scenarios (15 TR + 15 EN) in `eval/journeys.jsonl`, offline or live with an 8-call cap) → measured ETA error against observed
arrivals (`scripts/eta_report.py`, `eval/results/eta.md`).

| # | Rule | Incident or reference | Enforced by |
|---|---|---|---|
| T-1 | Tests never touch the network. | The gateway 503s every service after ~15 rapid calls (charter §1.4) | `_no_outbound_network` in `tests/conftest.py` fails any test that opens a non-loopback connection or DNS lookup, even if the code under test swallowed the error (since 2026-09-23; before that only tests using the `ctx` fixture were refused); `NABIZ_OFFLINE=1` in `make test` and CI |
| T-2 | **Test the surface that ships.** | The tool decorator lost `functools.wraps`; all twelve tools advertised `(*args, **kwargs)` and every call was rejected, while in-process tests stayed green | guardrail `mcp-schemas`; `make smoke`; `tests/test_mcp_integration.py` |
| T-3 | Every upstream trap becomes a regression fixture. | GTFS `stop_times.csv` cut at Excel's 1,048,575 rows; coordinates with thousands separators; the traffic endpoint answering XML without `Accept: application/json` | guardrails `csv-truncation`, `coordinate-sanity`; `tests/test_models.py`; `tests/test_http_cache.py` (the `Accept` header) |
| T-4 | **Fixtures are publication.** Scrub personal identifiers at capture and assert the fixture is synthetic. | The fleet fixture committed on 2026-09-08 carried 60 number-plate values as İBB served them; the `no-plate` guardrail exempts `tests/` because fixtures are verbatim responses | `scripts/capture_fixtures.py`; guardrail `fixture-plates-synthetic`; `tests/test_models.py::test_fleet_parsing_never_exposes_the_number_plate` |
| T-5 | An `xfail` is a documented, owned defect with a reason, never a way to get green. | 6 xfailed on the morning of 2026-09-23, from three markers in `tests/test_models.py` that record live defects. One of them turned a missing traffic index into 0, read to the user as "akıcı" (free-flowing), an invented reading; fixed the same day (`TrafficIndexPoint.index` is optional), which leaves 3 xfailed from two markers | review; no expiry check |
| T-6 | **The eval is the arbiter.** A feature without a scenario is not done; bad numbers are published. | `401ab4b` published an ETA error of 16.6 min rather than a placeholder | guardrail `no-fabricated-metrics`: every number in a README §Results row must be written in the `eval/results/` or `data/reference/` file that row names (until 2026-09-23 it only checked that `eval/results/latest.md` existed) |
| T-7 | **An in-sample fit is not accuracy.** | `c306157` reported the arrival error falling from 16.8 to 12.4 minutes, and the docs later quoted 11.2: both were the error of fitted rates *on the arrivals they were fitted to*. Accuracy is measured on estimates made after the fit is frozen, or on held-out data (`scripts/calibrate_eta.py` has a leave-one-hour-out hold-out; `eval/results/eta.md` explains both figures) | review |
| T-8 | Refuse rather than guess when the sample is thin. | `MIN_SAMPLES` in `src/ibb_mcp/eta_profile.py`; occupancy cells from one short window are rejected | `tests/test_eta_profile.py`, `tests/test_occupancy.py` |

Known gaps: numeric faithfulness and tool-call accuracy are `n/a` in the eval until an LLM is available
(DECISIONS #5); no property-based tests for the parsers of untrusted upstream data; no mutation proof in CI.

## 7. Security and supply chain

References: OpenSSF Scorecard checks — <https://github.com/ossf/scorecard/blob/main/docs/checks.md>;
SLSA v1.0 levels — <https://slsa.dev/spec/v1.0/levels>; MCP security best practices —
<https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices>.
Reporting and scope: [`SECURITY.md`](../SECURITY.md). Threat model: [`docs/THREAT_MODEL.md`](THREAT_MODEL.md).

**Scorecard, self-assessed.** The Scorecard tool has not been run on this repository; this is a reading of
each check against the files and the GitHub API on 2026-09-23.

| Check | State | Evidence |
|---|---|---|
| Token-Permissions | pass | `ci.yml`: top-level `permissions: contents: read` |
| Dangerous-Workflow | pass | no `pull_request_target`; no `${{ }}` inside `run:` |
| Pinned-Dependencies | **fail** on `main` | on `main`, actions pinned by tag and `uv` from an unpinned `curl \| sh`; the working tree pins every action to a commit SHA and installs `uv` 0.11.14 with `pip --require-hashes` from `.github/requirements-uv.txt`; the project's own dependencies have no lockfile either way |
| Branch-Protection | **fail** | `protected: false`, no ruleset |
| Code-Review | **fail** | 0 pull requests |
| CI-Tests | runs, red on `main` | §1; the working tree passes `make ci-local` |
| Security-Policy | pass once merged | `SECURITY.md` (this change); private reporting still off |
| Dependency-Update-Tool | **fail** | no Dependabot or Renovate configuration; alerts off |
| SAST | **fail** | no CodeQL; ruff selects `E, F, I, UP, B, SIM` and the size rules `C90, PLR0912, PLR0913, PLR0915` (§13), not `S` |
| Vulnerabilities | unknown | no `pip-audit` / `osv-scanner` run — not run |
| Binary-Artifacts | pass | `git ls-files` holds no binary |
| License | pass | `LICENSE` (MIT); data licence in `NOTICE.md` |
| Signed-Releases, Packaging, SBOM | n/a | no release exists |

**SLSA: Build L0.** No release artefact is built by CI and no provenance exists. L1 needs provenance for a
built artefact; L2 needs it generated and signed by a hosted build platform. The planned PyPI publish
(trusted publishing, <https://docs.pypi.org/trusted-publishers/>) and a container image built in CI are the
natural first artefacts to attest.

| # | Rule | Incident or reference | Enforced by |
|---|---|---|---|
| SC-1 | No secrets in the repository, CI reads none. | Public repo: a key pushed once is leaked forever | GitHub push protection; guardrail `no-secrets` |
| SC-2 | Pin actions to a full commit SHA; pin tools by hash, not only by version. | Scorecard Pinned-Dependencies; tag-hijack attacks on popular actions; an installer piped into `sh` runs whatever its URL serves | `ci.yml` in the working tree (actions by SHA, `uv` by wheel hash in `.github/requirements-uv.txt`); no lockfile for the project's dependencies yet |
| SC-3 | Dependency alerts stay on. A bot's update PR is never merged as the bot: the owner re-makes the change. A security control is never removed for a cosmetic reason. | Previous project deleted Dependabot because the bot showed up as a contributor, and replaced it with nothing (§11) | owner setting |
| SC-4 | Standard scanners before custom ones: secret scanning, dependency audit, SAST. | Principle 5 | secret scanning only |
| SC-5 | Tools are parametric: no free-form SQL/KQL, no URL argument (no SSRF surface), İBB text enters the agent as data. | DECISIONS #2; MCP security best practices | review; `tests/test_mcp_integration.py` for schemas |
| SC-6 | Nothing personal or machine-specific in tracked files. | `c68c6ba` stopped tracking a collector log that carried local paths; 19 early commits carry a personal e-mail in their metadata, which only a history rewrite could remove | guardrail `no-personal-data` (e-mail, home paths); hostnames and hardware: review |

## 8. Responsible AI

Reference: Microsoft's six Responsible AI principles — <https://www.microsoft.com/en-us/ai/principles-and-approach>.
Each principle is tied to a behaviour in the code and to the test or file that holds it, plus the gap.

| Principle | Concrete feature | Evidence | Gap |
|---|---|---|---|
| Transparency | **Provenance on every number**: every tool returns a `ToolResult` with source URL, `reported_at` and data age; ETA states its method and whether its rate was measured. **Unofficial-status notice** in the server instructions, the web UI badge and `NOTICE.md` | `src/ibb_mcp/models.py` (`Provenance`, `ToolResult`); `test_tools_return_data_with_provenance_over_the_wire`; `src/ibb_mcp/server.py`; the badge asserted in `tests/test_web.py` | 5 of 17 calls in the committed live eval carry an upstream timestamp (`eval/results/latest.md`) |
| Reliability and safety | **Off-route refusal**: no estimate for a stop the line does not serve. **Numeric faithfulness check**: every number in an answer must appear in a tool result. Thin samples refuse | `src/ibb_mcp/tools.py`; `test_arrivals_refuse_a_stop_the_line_does_not_serve`; eval scenario `j2-tr-2`; `src/nabiz/agent/faithfulness.py` + `tests/test_faithfulness.py` | faithfulness never measured on a real model |
| Privacy and security | **No personal data**: plates dropped at parse; alert subscriptions stay on the device, the server logs no coordinate and writes nothing to disk | DECISIONS #7; `docs/privacy.md`; `tests/test_alerts.py` | ingress access logs must be minimised before launch (`docs/privacy.md` §4) |
| Inclusiveness | Turkish-first, 15 TR + 15 EN scenarios; lift/escalator data per station; a deterministic no-LLM mode so access does not depend on a paid model | `eval/journeys.jsonl`; charter §1.6 | no accessibility audit of the web UI |
| Fairness | The data layer is an open, MIT-licensed MCP server any client can use, not a privileged path for our own agent | DECISIONS #2 | no evaluation of answer quality across districts |
| Accountability | A human owner authors and answers for every commit; the eval harness publishes bad numbers; decisions are recorded | DECISIONS.md; `eval/results/`; §5 | eval not yet a merge gate |

## 9. Azure Well-Architected and Twelve-Factor

References: Azure Well-Architected Framework — <https://learn.microsoft.com/en-us/azure/well-architected/>;
The Twelve-Factor App — <https://12factor.net/>. Nothing is deployed yet, so these are design choices
checked in code and templates, not observed behaviour.

| Pillar | Concrete choice | Evidence |
|---|---|---|
| Reliability | **Stale-on-error cache**: a gateway 503 returns the last value marked `cached` with its age, never a failure or a guess; single-flight; exponential backoff; the history store is optional and its tools answer `available: false` | `src/ibb_mcp/cache.py`; `test_cache_serves_stale_data_when_the_loader_fails`; DECISIONS #1, #3 |
| Security | Keyless upstream; managed identity planned; secret scanning; parametric tools | §7 |
| Cost optimisation | **Scale to zero**: Container Apps `minReplicas: 0` inside the monthly free grant; ADX free cluster; a do-not-provision list | `infra/modules/containerapps.bicep`; charter §1.6 — gap: no budget alert in the Bicep |
| Operational excellence | IaC (Bicep + `azd`), CI, guardrails, decision log; the collector runs under a supervisor after dying silently twice | `infra/`; `0951bcc`; gap: CI red (§2) |
| Performance efficiency | Per-source TTLs from how fast each upstream moves; one replica on purpose, because the İETT budget lives in process | DECISIONS #3; `maxReplicas` comment in `infra/modules/containerapps.bicep` |

| Factor | Choice here | State |
|---|---|---|
| I Codebase | one repo, two packages (`ibb_mcp`, `nabiz`) | DECISIONS #8 |
| II Dependencies | declared with extras in `pyproject.toml` | **no lockfile** (CD-2) |
| III Config | environment only: `Settings.from_env()` (`NABIZ_*`), LLM chosen by `LLM_*` | `src/ibb_mcp/config.py`; DECISIONS #5 |
| IV Backing services | ADX, Blob, the LLM endpoint attached by configuration | DECISIONS #1, #5 |
| V Build, release, run | `azd` from a laptop | no image or artefact yet |
| VI Processes | alert engine stateless; MCP server keeps cache and budget in process | deliberate deviation, capped at one replica |
| VII Port binding | `ibb-mcp --transport http --port`, `uvicorn` | `Makefile` |
| VIII Concurrency | scale-out blocked until cache and budget are shared | `containerapps.bicep` |
| IX Disposability | **politeness client** and stale-on-error make restarts cheap; supervisor restarts the collector | `src/ibb_mcp/http.py`; `scripts/supervise_collector.sh` |
| X Dev/prod parity | tests read only committed data (DECISIONS #17) | **holds** since `1599c40`: offline tests read the committed `tests/fixtures/gtfs_mini/` (CI-4) |
| XI Logs | stdout; logs never tracked | stdout; no log file is tracked (`git ls-files logs` prints nothing) |
| XII Admin processes | one-off scripts in `scripts/` | `scripts/README.md` |

## 10. Documentation and decisions

| # | Rule | Incident or reference | Enforced by |
|---|---|---|---|
| DC-1 | A decision that is expensive to reverse gets an entry in `DECISIONS.md`; a bad one is superseded, not deleted. | Nygard, <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions> | review |
| DC-2 | A number in a doc cites its source file or command, or it is not written. | Charter §1.5. Until 2026-09-23 `docs/positioning.md` presented the in-sample 11,2-minute fit as the arrival error (T-7) | README §Results only (`no-fabricated-metrics`, number by number against the file each row names); everywhere else, review |
| DC-3 | One fact lives in one file; others link to it. Rule files carry a "last verified" date. | Previous project: agent instructions and architecture docs contradicted the code (§11) | review |
| DC-4 | Status sections are updated in the change that makes them stale. | README "Project status" described Day 0 (CI, collector, agent listed as planned) until the refresh of 2026-09-23 | review |

---

## 11. Lessons carried over from the previous project

Two private reviews of the owner's previous project (DOU-Synapse, a course-assistant RAG app built by a team)
were written on 2026-09-22: a repository review and a maturity scorecard on the scale at the top of this
file. They are not in this repository and they describe a team's work, so this section keeps their lessons
and quotes none of their figures; nothing below can be re-derived from here, and nothing below is a number.

Their shared conclusion: the design was well above average — actions pinned to SHAs, least-privilege tokens,
tests that deliberately break a policy to prove they go red, honest "not run" labels — but **the gates did
not stop merges, red became normal, and the delivery machinery never ran once.**

**The weakest areas there, and the rule here that answers each.**

| Area | What happened there | Rule here | State here, 2026-09-23 |
|---|---|---|---|
| Disclosure policy | no `SECURITY.md` existed | §7, [`SECURITY.md`](../SECURITY.md) | added; private reporting still off |
| Container image scanning | the shipped image was never scanned | SC-4: scan the image digest once a Dockerfile exists | a `Dockerfile` in the working tree; no scan |
| Stop the line | `main` CI was almost never green and stayed red for days; a written note allowed a check to stay red | CI-3 | **repeated** until 2026-09-23: 13 runs red, then green (§1); still ungated |
| Release artefact built from the lock | tests used the lockfile, the image installed open ranges | CD-2 | **repeating in advance**: no lockfile |
| Trunk-based development | lanes merged big-bang through an integration branch, then reverted | CD-3, AI-2 | lane work uncommitted for 10 days |
| Dependency updates | Dependabot was removed because the bot appeared as a contributor, and nothing replaced it | SC-3 | alerts off; no update tool |
| Fuzzing / property tests | none for untrusted input | §6 gap | none for İBB parsers |
| Load and capacity test | none | not yet a rule: one replica by design | none |
| Merge gate | `main` unprotected; most commits bypassed pull requests | CI-3, §12 owner action | **repeating**: unprotected, 0 PRs (§1) |
| Deploy, rollback, DORA | no deployment; every deploy run skipped; no DORA metric defined | CD-1, CD-5, §4 | 0 deployments; no deploy workflow written — correctly |
| Agent instructions as code | `AGENTS.md` pointed at a long-stale branch; skill copies diverged | AI-1 | `AGENTS.md` dated, points to the charter |
| Process proportionality | governance documents and approval records grew to the size of the product, and nobody's gate read them | principle 6 | 5,059 lines of Markdown vs 12,647 of product Python at `c68c6ba` (§1) |
| Personal and machine data | personal and machine metadata in tracked files | SC-6 | guardrail `no-personal-data` in CI, green since `1599c40` |

**Carried over on purpose:** proving a gate can go red; honest `not run` / `n/a (reason)` labels that are
never upgraded; `CLAUDE.md` as a thin import of `AGENTS.md`; least-privilege workflow tokens; guardrails
that scan the whole tree, not just the diff (the previous project's diff-only checker kept passing over a
fabricated record already on `main`).

**Left behind on purpose:** dossier and approval records nobody's gate reads, integration branches, gates
parked in warn-only mode, custom checkers written before the standard tool, delivery pipelines written
before the first deployment.

---

## 12. Maturity self-assessment

Scored on the scale at the top, on 2026-09-23, for this repository including this change. One adjustment is
stated rather than hidden: **while `main` is unprotected and its CI has never been green, no row that relies
on CI can score above 2** — a check that is always red cannot tell a new failure from the old one, and
nothing stops a red change from landing anyway.

The integration batch of 2026-09-23 closes several "next steps" below in the working tree (the committed
GTFS subset, guardrails and the authorship gate in `ci.yml`, SHA pins, the `Dockerfile`, 17 ADRs, a
refreshed README). It was pushed the same night and its first run on `main` was green (`1599c40`, §1). The
scores below were set before that run and have not been re-scored, except Incident guardrails (1 to 2, on
the evidence in §1); the rest is the owner's call.

| Area | Score | Evidence | Next step to +1 |
|---|---:|---|---|
| CI pipeline | 2 | `ci.yml` runs on every push and PR; 13 runs, all red (§1) | fix CI-4, protect `main` → 3 |
| Keeping `main` green | 0 | red for 14.7 days; green since `1599c40` (2026-09-23), not yet gated; score not revised since | CI-3 |
| Merge gate and review | 0 | `protected: false`, no ruleset, 0 PRs | stage 1 (no force push, no deletion) now; the required CI check only with a rehearsed pull-request flow. Until then: `make ci-commit` before the push (or the pre-push hook) and `gh run watch` after it (owner) |
| Trunk-based integration | 1 | all commits straight to `main`; two lanes uncommitted since 2026-09-13 | land or close the two lanes |
| Continuous delivery | 1 | Bicep compiles in CI; 0 deployments; no lockfile, no Dockerfile | `uv.lock`, then first `azd up` |
| DORA measurement | 1 | measured once, by hand, in §4 | read-only scheduled measurement |
| Tests | 2 | suite passes locally (§1); network refused; over-the-wire MCP test; red on every runner so far | green in CI + gate → 3 |
| Eval harness | 2 | 30 scenarios (J5 added 2026-09-23); results in `eval/results/`; run by hand; its selftest now runs in the suite | `make eval` in CI |
| Incident guardrails | 2 | tracked, and a blocking CI step since `1599c40` (§1) | a ruleset on `main` requiring the CI check (owner) → 3 |
| Authorship and identity | 2 | 0 AI trailers in 21 commits; 2 of 21 on the noreply address; `.claude/settings.json` | `scripts/check_authorship.py` in CI |
| Secrets | 3 | GitHub push protection blocks known secret shapes at push | the owner procedure in [`SECURITY.md`](../SECURITY.md), "Handling keys" |
| Personal data and privacy | 2 | plate drop and alert privacy tested; a public fixture carried plate values until 2026-09-23 | privacy guardrails running in a green, blocking CI → 3 |
| Supply chain | 1 | read-only token; tag pins, unpinned installer, no lock, no scanning | SHA pins, `uv.lock`, alerts, `pip-audit` |
| Disclosure and threat model | 1 | `SECURITY.md`; private reporting off; threat model in progress | enable private reporting |
| Responsible AI in the product | 2 | provenance, off-route refusal, the faithfulness checker and the UI's unofficial badge are all under test (§8) | faithfulness measured on a real model (the "akıcı" defect of T-5 is fixed and pushed) |
| Operations and observability | 1 | `/healthz`; supervised collector; tracing wired in the agent; nothing deployed | deploy, then one availability probe and one freshness alert |
| Cost governance | 2 | scale-to-zero and one-replica cap in Bicep; do-not-provision list | budget alert in Bicep |
| Documentation and decisions | 2 | 9 ADRs, charter, privacy doc; drift in README status and positioning (§10) | fix the drift; date every rule file |
| AI-SDLC process | 2 | protocol, briefs and handoffs written (charter §5); lanes own files | eval-gated merge in CI; lanes land within a day |

Unweighted mean: **1.53** over 19 areas (1.47 before the guardrails row moved). It is not comparable with the
previous project's scorecard, which averaged a much finer-grained list of principles. The fastest movers are
owner actions that take minutes: a ruleset on `main`, private vulnerability reporting, Dependabot alerts — plus
one test fix (CI-4).

---

## 13. Modular code (MOD)

**Rule, one sentence:** put code in the lowest layer that can own it, import only downward, give every public
name one meaning, and never let a module, class or function that is already too big get bigger.

References: the measured import graph and size survey behind these rules (design review of 2026-09-23, kept
outside the repository); McCabe, *A Complexity Measure* (1976) for the threshold of 10; ruff's rule docs,
<https://docs.astral.sh/ruff/rules/>. Machine check for all of MOD-1 to MOD-6: `scripts/check_architecture.py`
(`make architecture`, CI step "Architecture fences"), each check shown red on a synthetic tree in
`tests/test_check_architecture.py`. The fences fail closed: a `nabiz.<app>` package that is not declared,
and a module under no dependency set, fail rather than pass by being in no table. The baseline of today's
debt is `scripts/architecture_baseline.json`; entries are meant only to go down (`make
architecture-tighten`), but nothing compares the file with the committed one, so raising an entry is a
review matter and needs its reason in the commit.

| # | Rule | Why (incident or reference) | Check |
|---|---|---|---|
| MOD-1 | **Import layers.** Inside `ibb_mcp` a module imports its own layer or a lower one: foundation (`config`, `models`, `cache`, `http`, `reference`, `telemetry`, `text`) → `sources` → domain (`eta`, `eta_context`, `eta_live`, `eta_schedule`, `eta_profile`, `gtfs`, `lines`, `metro_graph`, `occupancy`, `reliability`, `traffic_profile`) → services (`routing`, `analytics`, `alerts`) → facade (`tools`) → transport (`server`) → the `nexus_core` library → the `nabiz` apps. **`ibb_mcp` never imports `nabiz`.** `nexus_core` imports nothing from `ibb_mcp` or `nabiz` (`LIBRARY_IMPORTS`, DECISIONS #21). Sources never import each other, only `sources.base`. The apps (`nabiz.web`, `.agent`, `.collector`, `.alerts`) never import each other, and the agent and the web page reach İBB data through `ibb_mcp.tools` (DECISIONS #2). Lazy imports count. | DECISIONS #8 held "only because nothing is reviewing it"; on 2026-09-23 four `ibb_mcp` imports reached into `nabiz` and `import ibb_mcp.server` loaded seven `nabiz` modules; two sources imported other sources for a text helper; the agent bypassed the facade for the same helper. Fixed by DECISIONS #19 | `layers`; dated `LAYER_EXCEPTIONS` only shrink (a stale one fails) |
| MOD-2 | **No import cycles**, lazy ones included. | A cycle makes import order load-bearing and turns every split into an untangling job; zero on 2026-09-23 | `no-cycles` |
| MOD-3 | **Declared dependency sets.** Beyond the standard library a package imports only what its install extra declares: `ibb_mcp` `httpx`, `pydantic`, `mcp` (the transport also the SDK's own `starlette`, `uvicorn`; tracing the optional `opentelemetry`, `azure`); `nabiz.web` plus FastAPI; `nabiz.collector` plus Azure, Delta; `nabiz.agent` plus the model clients. | DECISIONS #8: installing `ibb-mcp` pulls three runtime packages. Nothing else noticed a fourth | `dependency-sets` |
| MOD-4 | **Function size (ruff).** C901 max-complexity 10, PLR0912 max-branches 12, PLR0913 max-args 7, PLR0915 max-statements 50. Max-args is 7, not ruff's 5, because an MCP tool's parameters are its public schema and the widest facade tool takes 7. Existing violations carry `# noqa: <rule> - debt, ratcheted in scripts/architecture_baseline.json` on the `def` line, or a per-file ignore in `pyproject.toml` for a file another lane owns. | `build_server` scored 22 with one nested closure per tool; `create_app` 26. Registration functions grow a branch with every feature. On 2026-09-23 a review showed that raising a threshold or adding an `extend-exclude` in `pyproject.toml` turned a real regression into "improved" | `make lint`; `complexity` re-runs ruff `--isolated` with the thresholds as constants in the script (a test holds `pyproject.toml` equal to them), `--ignore-noqa` and only the policy ignore (`tests/**` PLR0913), so debt may get simpler, never worse, a new violation fails, and a grandfathered function ruff stops reading fails |
| MOD-5 | **Module size, ratcheted.** At most 400 code lines per module in `src/` (blank, comment and docstring lines are free: comments explain *why* here). A module over the cap may shrink, never grow, not even by a line; a fix that must touch one extracts something in the same change. | `src/ibb_mcp/tools.py` went from 445 lines at `c68c6ba` to 885 at `d59b5a8`, the same day (`git show <commit>:src/ibb_mcp/tools.py \| wc -l`); the modules over the cap are exactly those with more than one reason to change | `module-size` |
| MOD-6 | **Public surface.** One public top-level name, one definition (`main` allowlisted; re-exports and aliases are not definitions). No import of another module's `_private` name in `src/` or `scripts/`, relative imports and one script importing another included (tests may). A class has at most 250 code lines and 15 public methods. `__all__` in a package `__init__.py` that re-exports: review only. | Three `normalize_tr` functions folded Turkish three ways (`ibb_mcp.text` is now the one home); the `Nabiz` facade holds every tool in one class | `one-meaning`, `private-imports`, `class-size` |
| MOD-7 | **Split by responsibility, one behaviour-preserving step per commit**, proven by the suite, `make smoke` and guardrail `mcp-schemas`; public import paths kept by re-export or alias. | A split by line count moves the problem; a split that changes the MCP contract breaks every client | review; the steps are below |
| MOD-8 | **Front end without a build step:** one ES module per job, pure modules never touch the DOM, colours only in `css/tokens.css`. | Design spec §15 (FE-MOD; public form in [`docs/design/DESIGN.md`](design/DESIGN.md) §11); the old page's router could only be tested by evaluating all of `app.js` against a DOM stub | `scripts/check_web_budget.py` (`file-size`, `js-modules`, `tokens`, `css-prefix`, `listeners`, `icons`, `contract-ids`, `dashes`), CI step "Web budget"; the server's half of the no-dash rule is `tests/test_answer_text.py`. Today's redesign targets are listed in the script, and a met one must be deleted; a raised one is a review matter with its reason in the commit |

**Split plan.** Done on 2026-09-23: S0 (alert engine → `ibb_mcp.alerts`, tracing → `ibb_mcp.telemetry`), S1
(`ibb_mcp.text`), S2 (`ibb_mcp.reference.parse_once`, one cache for the three reference tables), S3
(`build_server` → five `_register_*` groups, complexity 22 → 3; tool names, order and input schemas
byte-identical, while the descriptions of `iett_next_arrivals` and `plan_journey` changed on purpose for
DECISIONS #18), the first step of S7 (`nabiz.agent.schemas`). Next, each when its module is next touched,
because the ratchet makes "touch it, shrink it" the only option: S3b the HTTP edge of `server.py`
(`TokenBucket` … `HttpGuard`) into its own module; S4 `nabiz.web.main.create_app` into an `APIRouter`
(web lane); S5 `ibb_mcp.tools` into a package of mixins (a delegate would repeat every tool signature,
which is the MCP schema); S6 `routing.py` into `routing/` with a `JourneyRequest` parameter object; S7 the
rest of `agent.py` (router table, renderers); S8 `reliability.py` and `occupancy.py` into packages. Done on 2026-09-28: S9 `eta.py` (494 code lines) into `eta_context` (vocabulary,
`EtaParams`, `EtaContext`), `eta_live` (stop-sequence and distance methods) and `eta_schedule` (GTFS and İETT
timetable fallbacks, `planned_summary`); `eta.py` keeps `estimate_arrivals`, `speed_profile_from_fleet` and
re-exports the public names, so every `from ibb_mcp.eta import X` still resolves.

**Alternatives considered.** `import-linter` expresses layers and cycles but not the ratchets or the
dependency sets, and would add a dependency; ruff `TID251` with a nested config can ban `nabiz` from
`ibb_mcp` at editor time and is a good echo of MOD-1, not a replacement; a physical-line cap was rejected
because it taxes comments.

## 14. Optimisation (OPT)

**Rule, one sentence:** measure before optimising, budget what the product actually pays for (the shared
İBB request budget, cold start, first paint on a phone), and count it rather than time it.

Warm tool latency is single-digit milliseconds offline (`make perf-report`), so it gets only a backstop.
The binding constraints are external and countable: İBB's gateway (503s after ~15 rapid calls; İETT
documents 100 an hour; `PoliteClient` stops at 80), the scale-to-zero cold path, and the page's round trips.
The harness is `scripts/perf_report.py`; `tests/test_performance_budgets.py` asserts with the same code,
so a number in a commit and a number CI enforces cannot drift apart.

| # | Rule | Why | Check |
|---|---|---|---|
| OPT-1 | **Before and after, same machine.** A change that claims to be faster or cheaper carries `make perf-report` (or `make web-budget`) output from before and after in its commit body. | "Faster" without numbers is a claim nobody can check (charter §1.5) | **none**: review. There are no pull requests to lint, so a PR-body check would never run |
| OPT-2 | **Upstream calls per tool:** a budget per MCP tool on a cold cache, 0 when warm; a new tool fails until it has a budget line and a sample call. Each cold cost also fits the tool's public price in `TOOL_COSTS` (1 per answer, 1 per gateway call, 4 per İETT call). Counted at the cache and at the boundary (a recorded response read offline, a request reaching the client), the larger of the two, because nothing but review forces a source through the cache. | DECISIONS #3 and #15: the gateway budget is shared with everyone, and an undercharged tool lets one caller spend it. On 2026-09-23 a review showed a second read beside the cache passing every gate, because only the cache was counted | `test_upstream_calls_cold_within_budget_and_zero_when_warm`, `test_the_public_price_covers_what_a_cold_call_costs`, `test_every_tool_has_an_upstream_budget_and_a_sample_call`, `test_the_harness_counts_a_read_beside_the_cache` |
| OPT-3 | **Cache behaviour through the real tool path:** 50 concurrent cold questions cost what one costs (single flight); an expired entry whose reload fails is served marked `cached` (stale-on-error); `DEFAULT_TTL` equals DECISIONS #3's table. **One hot line fits the İETT budget:** a line asked about continuously costs 3600/90 + 3600/120 = 70 İETT calls an hour against the budget of 80. At the old 60 s line TTL it cost 90, and after about 53 minutes every İETT answer went stale (DECISIONS #3, 2026-09-23). | A TTL is an upstream bill; a TTL change has to change the ADR too | `test_fifty_concurrent_questions_cost_what_one_costs`, `test_an_expired_entry_is_served_stale_when_the_upstream_fails`, `test_ttls_match_the_documented_table`, `test_one_hot_line_fits_the_hourly_iett_budget` (the arithmetic exactly, so a TTL change in either direction turns it red) |
| OPT-4 | **Work once per process:** the GTFS index, stop sequences, the gazetteer and each reference table are parsed at most once per process per file version (`ibb_mcp.reference.parse_once`); the default arrival mode never reads the ETA profile. | Until 2026-09-23 the reliability table and the ETA profile were parsed on every call, and they grow with the history the collector keeps adding | `test_expensive_loads_happen_at_most_once_per_process` (spies over 20 rounds, both ETA modes); `test_the_harness_counts_a_parse_moved_onto_the_request_path` proves the spy can go red |
| OPT-5 | **Latency backstop, wide margin:** warm p95 ≤ 50 ms per tool over 30 calls, cold offline ≤ 500 ms. The measured values and the margin are stated beside the constants. | Catches an order-of-magnitude regression (a real-GTFS parse on the request path, an accidental sleep) without failing on a slow shared runner | `test_warm_latency_backstop` |
| OPT-6 | **GTFS on the committed mini fixture:** index load and sequence build each ≤ 250 ms and ≤ 4 MiB tracemalloc peak. tracemalloc counts allocations, so the memory budget is the machine-independent one. The real export is laptop-only; its numbers are re-measured by hand, never in CI. | On the laptop's full export (2026-09-23): index load 0.27 s for 15,386 stops; a full sequence rebuild from `stop_times.txt` 8.62 s for 2,876 routes, with the process peaking at 584 MiB RSS (`/usr/bin/time -l` around `GtfsIndex.load` and `build_stop_sequences`), against the 1 GiB container in `infra/modules/containerapps.bicep`. That is why `.dockerignore` leaves `stop_times.*` and `trips.csv` out | `test_gtfs_mini_index_and_sequences_stay_small` |
| OPT-7 | **Cold start stays light:** `import ibb_mcp.server` in a fresh interpreter loads none of `nabiz`, `fastapi`, `azure`, `openai`, `deltalake`, `pyarrow`, `agent_framework`. Wall-clock import time is reported, not gated: it measures the SDK and the machine more than this code. | Every VS Code or Claude session starts the server; DECISIONS #8 | `test_importing_the_server_loads_no_app_and_no_optional_extra` |
| OPT-8 | **The page:** first-party bytes (raw and gzip), no third-party render-blocking resource, fonts, layout-free motion with a reduced-motion path checked by structure (and scripted motion only in `js/motion.js`), token-only colours. Core Web Vitals are measured in the lab by hand (Lighthouse, mobile preset, median of 3), never a CI gate: the page pulls MapLibre and tiles from third parties and lab scores on shared runners move between runs. | Design spec §15 (FE-OPT; [`docs/design/DESIGN.md`](design/DESIGN.md) §11); first paint on a phone is round trips, not bytes | `scripts/check_web_budget.py` (`payload`, `render-blocking`, `third-party`, `fonts`, `motion`), CI step "Web budget"; Web Vitals: **none in CI** |

