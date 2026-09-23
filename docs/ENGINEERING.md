# Engineering handbook

How this repository is built, rule by rule. Every rule is tied either to an incident this repository has
already had or to a named reference with a link, and every rule says what enforces it — or that nothing
does yet. [`AGENTS.md`](../AGENTS.md) is the short, binding version for coding agents;
[`docs/NABIZ.md`](NABIZ.md) is the charter. This file is the *why*.

Last verified: 2026-09-23, against `main` at `c68c6ba` plus the uncommitted working tree of that day.

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
| Commits on `main` | 21 (20 pushed; `c68c6ba` local) | `git rev-list --count HEAD` |
| Pull requests ever opened | 0 | `gh api 'repos/muratcan-ates/istanbul-nabiz/pulls?state=all' --jq length` |
| `main` protected / rulesets | `protected: false` / `[]` | `gh api repos/muratcan-ates/istanbul-nabiz/branches/main --jq .protected`; `gh api repos/muratcan-ates/istanbul-nabiz/rulesets` |
| CI runs on `main` | 13, **13 failed**, 0 cancelled | `gh run list --workflow ci.yml --branch main --limit 100` |
| Why they fail | 10 runs: the same 3 tests in `tests/test_web.py`, which read GTFS files under the gitignored `data/reference/gtfs/` (176 MB locally), so the runner has none. 3 runs on 2026-09-13: the ruff gate (2 errors), so pytest never ran. Fixed in the working tree on 2026-09-23 (`tests/fixtures/gtfs_mini`, DECISIONS #17; `make ci-local` passes on a clean copy); not pushed, so no green run exists yet | `gh run view <id> --log-failed` |
| First and latest CI run | 2026-09-08 08:49 UTC · 2026-09-22 18:25 UTC — red for 14.4 days, never green | same |
| CI duration (queued to completed) | median 23 s, range 17–38 s (n = 13) | `createdAt`/`updatedAt` from `gh run list --json` |
| Local test suite | 943 passed, 1 skipped, 3 xfailed on the integrated working tree, and the same on the clean copy `make ci-local` builds (2026-09-23, after the review fixes) | `NABIZ_OFFLINE=1 .venv/bin/python -m pytest -q` |
| `scripts/guardrails.py` | 12 checks, 0 failed, 1 warning on the working tree (the warning is a truncated local file the loader never reads); a blocking step in the working-tree `ci.yml`, not pushed | `NABIZ_OFFLINE=1 .venv/bin/python scripts/guardrails.py` |
| Deployments | 0 | `gh api repos/muratcan-ates/istanbul-nabiz/deployments --jq length` |
| Secret scanning / push protection | enabled / enabled | `gh api repos/muratcan-ates/istanbul-nabiz --jq .security_and_analysis` |
| Dependabot alerts · security updates | off (HTTP 404) · disabled | `gh api -i repos/muratcan-ates/istanbul-nabiz/vulnerability-alerts` |
| Private vulnerability reporting | disabled | `gh api repos/muratcan-ates/istanbul-nabiz/private-vulnerability-reporting` |
| Commit identity | 2 of 21 commits use the noreply address; 0 carry a co-author trailer or an assistant footer | `git log --format='%ae'`; `git log --format=%B \| grep -ciE '^co-author\|generated (with\|by)'` |
| Lane branches from 2026-09-13 | `feat/route-advisor`, `feat/ops-hardening`: 0 commits past `401ab4b`, their work uncommitted in two worktrees; `main` is 5 commits ahead. Both harvested into the working tree on 2026-09-23 (outcome per file in `docs/route-advisor.md` §9, DECISIONS #11, #15, #16); the worktrees can go once that lands | `git worktree list`; `git rev-list --count 401ab4b..main` |
| Markdown vs product code (tracked at `c68c6ba`) | 5,059 lines of Markdown; 12,647 lines of Python under `src/` (the working tree adds to both) | `git grep -h -c '' HEAD -- '*.md' \| awk '{s+=$1} END {print s}'`; the same with `'src/*.py'` |

The single most important line in that table is the fourth. It is the failure the previous project was
reviewed for (§11), repeating here in smaller form.

---

## 2. Continuous integration

Reference: Martin Fowler, *Continuous Integration* —
<https://martinfowler.com/articles/continuousIntegration.html> ("every push to mainline should trigger a
build", "fix broken builds immediately", "keep the build fast", "make the build self-testing").

| # | Rule | Why (incident or reference) | Enforced by | State |
|---|---|---|---|---|
| CI-1 | Every push to `main` and every pull request runs CI; the pipeline is code in the repo. | Fowler | `.github/workflows/ci.yml` | holds |
| CI-2 | Local equals CI: one command runs the gate list CI runs. | "It passed locally" is only useful if locally means the same checks | `make ci-local` (added with this sprint's CI change) | holds locally (green on a clean copy, 2026-09-23) |
| CI-3 | **Stop the line.** While `main` is red, the only change that merges is the fix. No "this check may stay red". | §1: 13 of 13 runs red for 14.4 days. Two lint errors landed on 2026-09-13 and failed three runs before pytest could start, looking exactly like the failure already there — red hid a new defect. The previous project's red `main` silently switched its delivery off (§11) | nothing yet — a ruleset requiring the CI check is the gate (owner, §12) | **broken** |
| CI-4 | **Hermetic tests.** CI must not need a file that exists only on a laptop. | The three failing tests read `data/reference/gtfs/`, which is gitignored. They pass locally and fail on every runner — a dev/prod parity failure (Twelve-Factor X) | `tests/fixtures/gtfs_mini` behind the shared test settings; `make ci-local` copies only what a push publishes | fixed in the working tree, not pushed |
| CI-5 | Keep the build fast; never cancel a run on `main`. | Fowler. The previous project cancelled a large share of its `main` runs through `cancel-in-progress` | `ci.yml`: `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}` in the working tree (on `main` it is still `true` for every ref) | fixed in the working tree, not pushed |
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
| CD-3 | **Short-lived branches, integrated daily.** A lane that cannot land in a day is split. | DORA trunk-based development. §1: two lane worktrees from 2026-09-13 still hold uncommitted work ten days later, five commits behind `main` | review | **gap** |
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
| Failed deployment recovery time | undefined | time `main` CI stays red | never green: 14.4 days from first to latest run |
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
| AI-1 | Agent instructions are code: one short `AGENTS.md`, a `CLAUDE.md` that only imports it, dated, pointing to the charter instead of copying it. | Previous project: an `AGENTS.md` that pointed at a long-stale branch (§11); `AGENTS.md` convention <https://agents.md/>; Claude Code imports <https://code.claude.com/docs/en/memory> | guardrail `agent-rules-links`: every repository path and `make` target named in `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md` exists |
| AI-2 | **One lane, one worktree, one file list.** | On 2026-09-13 two sessions edited one working tree at once. A branch does not isolate that: `git checkout` moves the tree under the other session, and two agents writing one file lose each other's edits with no conflict marker. The ops lane moved to its own worktree for that reason (handoff on the unmerged `feat/ops-hardening`) | review |
| AI-3 | **Lane agents never commit or push; staging is by explicit path.** | Previous project: concurrent sessions' `git add -A` swallowed another lane's work, and a lane's work was left uncommitted in a sandbox | review |
| AI-4 | **No AI attribution; noreply identity.** | Owner's rule, after an assistant appeared in a contributor list on an earlier project | `.claude/settings.json`, `.vscode/settings.json`; `scripts/check_authorship.py` (commits; before a push through `.githooks/pre-push` once `make hooks` has run); guardrail `no-ai-attribution` (files) |
| AI-5 | **A research brief names one subject and one repository, embeds the verified current state, and opens with a proof-of-reading gate.** | Commit `7cc0fc1`: the first brief linked only another project's repo, so the research model planned the wrong project, took a stale README section for current state and reported a 314-commit repository as a 10-commit MVP | review (`docs/research_prompt_v2.md` is the template) |
| AI-6 | **When lanes collide, the first fix is less concurrency, not another gate.** | Previous project: every collision produced a new gate or document, never fewer agents | review |
| AI-7 | The owner's review goes to risky paths first: `src/ibb_mcp/{http,cache,models,server}.py`, `.github/`, `scripts/guardrails.py`, `infra/`. | Fowler/ISE code review; principle 7 | review |

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
| SAST | **fail** | no CodeQL; ruff selects `E, F, I, UP, B, SIM`, not `S` |
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
| X Dev/prod parity | **violated** — tests need gitignored GTFS data (CI-4) | §1 |
| XI Logs | stdout; logs never tracked | one log file is still tracked: `logs/mcp-http.log` |
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
| Stop the line | `main` CI was almost never green and stayed red for days; a written note allowed a check to stay red | CI-3 | **repeating**: 13 of 13 red (§1) |
| Release artefact built from the lock | tests used the lockfile, the image installed open ranges | CD-2 | **repeating in advance**: no lockfile |
| Trunk-based development | lanes merged big-bang through an integration branch, then reverted | CD-3, AI-2 | lane work uncommitted for 10 days |
| Dependency updates | Dependabot was removed because the bot appeared as a contributor, and nothing replaced it | SC-3 | alerts off; no update tool |
| Fuzzing / property tests | none for untrusted input | §6 gap | none for İBB parsers |
| Load and capacity test | none | not yet a rule: one replica by design | none |
| Merge gate | `main` unprotected; most commits bypassed pull requests | CI-3, §12 owner action | **repeating**: unprotected, 0 PRs (§1) |
| Deploy, rollback, DORA | no deployment; every deploy run skipped; no DORA metric defined | CD-1, CD-5, §4 | 0 deployments; no deploy workflow written — correctly |
| Agent instructions as code | `AGENTS.md` pointed at a long-stale branch; skill copies diverged | AI-1 | `AGENTS.md` dated, points to the charter |
| Process proportionality | governance documents and approval records grew to the size of the product, and nobody's gate read them | principle 6 | 5,059 lines of Markdown vs 12,647 of product Python at `c68c6ba` (§1) |
| Personal and machine data | personal and machine metadata in tracked files | SC-6 | guardrail `no-personal-data` in the working-tree CI, not pushed |

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
refreshed README). None of it is pushed, so the scores stay as they are until a green run on `main`.

| Area | Score | Evidence | Next step to +1 |
|---|---:|---|---|
| CI pipeline | 2 | `ci.yml` runs on every push and PR; 13 runs, all red (§1) | fix CI-4, protect `main` → 3 |
| Keeping `main` green | 0 | never green in 14.4 days | CI-3 |
| Merge gate and review | 0 | `protected: false`, no ruleset, 0 PRs | ruleset requiring the CI check (owner) |
| Trunk-based integration | 1 | all commits straight to `main`; two lanes uncommitted since 2026-09-13 | land or close the two lanes |
| Continuous delivery | 1 | Bicep compiles in CI; 0 deployments; no lockfile, no Dockerfile | `uv.lock`, then first `azd up` |
| DORA measurement | 1 | measured once, by hand, in §4 | read-only scheduled measurement |
| Tests | 2 | suite passes locally (§1); network refused; over-the-wire MCP test; red on every runner so far | green in CI + gate → 3 |
| Eval harness | 2 | 30 scenarios (J5 added 2026-09-23); results in `eval/results/`; run by hand; its selftest now runs in the suite | `make eval` in CI |
| Incident guardrails | 1 | `scripts/guardrails.py` written but untracked and not in CI on 2026-09-23 | track it, make it pass, wire it into CI → 3 |
| Authorship and identity | 2 | 0 AI trailers in 21 commits; 2 of 21 on the noreply address; `.claude/settings.json` | `scripts/check_authorship.py` in CI |
| Secrets | 3 | GitHub push protection blocks known secret shapes at push | add the `no-secrets` guardrail to CI; rotate-on-leak runbook |
| Personal data and privacy | 2 | plate drop and alert privacy tested; a public fixture carried plate values until 2026-09-23 | privacy guardrails running in a green, blocking CI → 3 |
| Supply chain | 1 | read-only token; tag pins, unpinned installer, no lock, no scanning | SHA pins, `uv.lock`, alerts, `pip-audit` |
| Disclosure and threat model | 1 | `SECURITY.md`; private reporting off; threat model in progress | enable private reporting |
| Responsible AI in the product | 2 | provenance, off-route refusal, the faithfulness checker and the UI's unofficial badge are all under test (§8) | faithfulness measured on a real model (the "akıcı" defect of T-5 is fixed in the working tree, not pushed) |
| Operations and observability | 1 | `/healthz`; supervised collector; tracing wired in the agent; nothing deployed | deploy, then one availability probe and one freshness alert |
| Cost governance | 2 | scale-to-zero and one-replica cap in Bicep; do-not-provision list | budget alert in Bicep |
| Documentation and decisions | 2 | 9 ADRs, charter, privacy doc; drift in README status and positioning (§10) | fix the drift; date every rule file |
| AI-SDLC process | 2 | protocol, briefs and handoffs written (charter §5); lanes own files | eval-gated merge in CI; lanes land within a day |

Unweighted mean: **1.47** over 19 areas. It is not comparable with the previous project's scorecard, which
averaged a much finer-grained list of principles. The fastest movers are owner actions that take minutes: a
ruleset on `main`, private vulnerability reporting, Dependabot alerts — plus one test fix (CI-4).
