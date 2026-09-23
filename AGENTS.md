# AGENTS.md — binding rules for AI coding agents

The single entry point for any AI coding agent working in this repository, whatever the tool.
Short on purpose, and binding. Last verified: 2026-09-23.

## 0. Read first

1. [`docs/NABIZ.md`](docs/NABIZ.md) — the charter: identity, hard rules, verified İBB facts, and the
   Integrator / Feature / Research protocol with its brief and handoff templates. This file does not repeat
   it. If the two disagree, the charter wins and this file is wrong: say so in your handoff.
2. Your brief: lane name, the files you own, the Definition of Done, what is out of scope.
3. [`docs/ENGINEERING.md`](docs/ENGINEERING.md) when you need the incident or reference behind a rule.

## 1. Ownership and lanes

- **One lane = one brief = one explicit file list.** Edit only the files your brief names. A change you need
  elsewhere goes into your handoff as the exact edit, for the Integrator to make.
- **One worktree per parallel lane**, created by the owner (`git worktree add ../nabiz-<lane> -b feat/<lane>`).
  Two agents in one working tree overwrite each other with no conflict marker to warn anyone. When a sprint
  does share one tree, per-file ownership is the only isolation: touch nothing outside your list.
- Never revert, reformat or "tidy" a file you do not own, even when it looks wrong. Report it instead.
- **Lane agents never commit and never push.** A commit happens after the owner has reviewed the diff —
  made by the owner, or by the Integrator session when the owner explicitly asks, always under the owner's
  identity. A lane hands over suggested commits: subject, body, and the exact file list, with every file it
  changed in exactly one commit.
- Lane agents do not run `git add`, `commit`, `push`, `stash`, `checkout`, `switch`, `reset`, `restore`,
  `clean`, `rebase`, `merge`, `worktree`, or anything that moves HEAD, changes the index or rewrites history.
  Read-only `git` (`status`, `diff`, `log`, `show`, `blame`, `ls-files`) and read-only `gh` are fine.
- Staging is by explicit path. `git add -A`, `git add .` and `git commit -a` are not used here: in a shared
  tree they sweep another lane's unfinished work into the commit. Nobody force-pushes.
- **Stop the line.** If CI on `main` is red, the only work that merges is the fix that turns it green.

## 2. Authorship: the owner is the author

- **No AI attribution anywhere.** No `Co-Authored-By`, no "Generated with", no assistant or model names in
  commit messages, PR text, code comments or docs. The owner is the author and answers for every line.
- Commit identity: `Muratcan Ateş <135648847+muratcan-ates@users.noreply.github.com>`. Never a personal
  e-mail — the history is public and permanent.
- No bot authors: no GitHub App or Action that commits, pushes or opens PRs as a bot. Dependabot *alerts*
  are welcome; a bot's version-bump PR is not merged — the owner re-makes the change under his own name.
- Claude Code reads `.claude/settings.json`, which switches its attribution off. Any other tool: before the
  owner commits, check `git log -1 --format='%an <%ae>%n%B'`.

## 3. Privacy: this repository is public

- Nothing personal or machine-specific in a tracked file: no e-mail except the noreply address above, no
  home-directory paths (write repo-relative paths), no hostnames, no hardware or subscription details, no
  tokens or keys, no real vehicle number plates.
- Bus number plates are dropped at the parser (`BusPosition.from_fleet_raw`, DECISIONS #7) and must not
  reappear anywhere — recorded fixtures included, because fixtures are published with the code.
- No personal data server-side (charter §1.3, KVKK). A user's location lives on their device;
  [`docs/privacy.md`](docs/privacy.md) is the design and names the tests that hold it.
- Logs, the data lake and raw eval JSON stay out of git (`.gitignore`). A tracked log once carried local paths.
  One exception is still tracked, `logs/mcp-http.log` (a 692-byte uvicorn log with no path in it), until
  the owner runs `git rm --cached logs/mcp-http.log`; the guardrails check it in the meantime.

## 4. İBB's gateway is shared public infrastructure

- **Never call `api.ibb.gov.tr` or any İBB host** from tests, CI, evals or exploration. Run Python with
  `NABIZ_OFFLINE=1`; tests read `tests/fixtures/`, and `tests/conftest.py` fails any test that tries the network.
- Every upstream call goes through `PoliteClient` (`src/ibb_mcp/http.py`) and the TTL cache
  (`src/ibb_mcp/cache.py`). No per-user upstream path, ever (DECISIONS #3).
- `make` targets marked NETWORK spend the shared budget. Only the owner runs them.
- The collector (`scripts/collect_forever.py` under `scripts/supervise_collector.sh`) may be running and owns
  the rate budget. Do not stop, restart or edit either file: bash re-reads a running script.

## 5. Honest numbers

- Every number you write comes from a file in the repo or a command you ran, and you say which.
- What you did not run, write as `not run: <reason>`. A metric that cannot be measured is `n/a (<reason>)`.
- An in-sample fit is not measured accuracy. Calibration results are labelled as fits; accuracy comes from
  `eval/results/` or from predictions scored after the fit was frozen.
- Never invent an API field, endpoint, price, model name, test count or URL. Leave a marked placeholder and ask.

## 6. Code conventions

- Python 3.12 from `.venv` only (`.venv/bin/python`, `.venv/bin/ruff`). Ruff line length 130.
- Comments explain *why*. Match the docstring voice of the surrounding code.
- Turkish display text: `tr_title` (`scripts/build_places.py`), never `str.title()` — it turns `i` into `I`, not `İ`.
- MCP SDK 2.x: `from mcp.server.mcpserver import MCPServer`, not `FastMCP`. The `@tool` wrapper in
  `src/ibb_mcp/server.py` keeps `functools.wraps`, or every schema collapses to `(*args, **kwargs)`.
- Tools are parametric and return a `ToolResult` with provenance. No free-form SQL, KQL or URL from a model.
- Put code in the lowest layer that can own it and import only downward ([`docs/ENGINEERING.md`](docs/ENGINEERING.md)
  §13, MOD-1). `ibb_mcp` never imports `nabiz`; the agent and the web app reach İBB data through `ibb_mcp.tools`;
  Turkish text keys come from `ibb_mcp.text`, never a local copy.
- A module over 400 code lines, a class over 250 code lines or 15 public methods, or a function over the ruff limits
  (complexity 10, branches 12, arguments 7, statements 50) is not extended: split it first, or leave it smaller
  than you found it. Today's debt is `scripts/architecture_baseline.json`. It is meant only to go down, but
  no check compares it with the committed file: raising an entry needs its reason in the commit (review).
- One public name, one definition. Never import another module's `_private` name.
- Do not optimise without numbers: `make perf-report` before and after (§14). Count upstream calls, parses and
  imports; do not tune milliseconds that are already small.

## 7. Definition of Done

- [ ] `make lint` clean on the files you touched
- [ ] `make test` green; new behaviour has new tests; `make smoke` still lists the expected tool count
- [ ] `make guardrails` reports no FAIL, and `make authorship` passes
- [ ] `make architecture` reports no FAIL (a WARN means: run `make architecture-tighten` and commit the lower
      baseline); `make web-budget` too when the page changed
- [ ] a new MCP tool has an upstream budget line and a sample call (`tests/test_performance_budgets.py`,
      `scripts/perf_report.py`); an optimisation claim carries before and after `make perf-report` output
- [ ] a user-visible behaviour has a scenario in `eval/journeys.jsonl` (or a proposed `eval/journeys.<lane>.jsonl`)
      and `make eval` passes offline
- [ ] docs that describe the change are updated in the same change; README numbers only from the
      `eval/results/` or `data/reference/` file their row names
- [ ] every number sourced; everything not run says so and why
- [ ] handoff report in the charter's §5.3 format, with exact pass/fail counts

`make ci-local` runs the same gate list as CI. Report failures in files you do not own; do not fix them.

## 8. Where each rule is enforced

A rule with no machine check says so. "Review" means the owner reading the diff is the only gate.

| Rule | Machine check | Runs in |
|---|---|---|
| No AI trailer, no bot author, noreply identity in commits | `scripts/check_authorship.py`; `.githooks/pre-push` runs it before anything is public, once `make hooks` has set `core.hooksPath` | `make authorship`, `git push`, CI |
| No AI credit pasted into a file | guardrail `no-ai-attribution` | `make guardrails`, CI |
| Claude Code adds no attribution | `.claude/settings.json` (`attribution`) | local sessions |
| VS Code adds no Copilot co-author | `.vscode/settings.json` (`git.addAICoAuthor: off`) | local sessions |
| No number plate past the parser | guardrail `no-plate`; `tests/test_models.py`, `tests/test_collector.py`, `tests/test_web.py` | `make guardrails`, `make test`, CI |
| Fixture plates and plate examples are synthetic | guardrail `fixture-plates-synthetic` | `make guardrails`, CI |
| No İBB call outside `PoliteClient` | guardrail `no-raw-ibb-calls` | `make guardrails`, CI |
| No İBB call from tests or CI | `_no_outbound_network` in `tests/conftest.py` (every test: a non-loopback connection or DNS lookup fails it), `refuse_network` behind the `ctx` fixture; `NABIZ_OFFLINE=1` in `make test` and `.github/workflows/ci.yml` | `make test`, CI |
| Tool schemas keep real parameters | guardrail `mcp-schemas`; `make smoke`; `tests/test_mcp_integration.py` | local, CI |
| Every MCP tool has an eval scenario | `tests/test_eval_harness.py` (the harness selftest) | `make test`, CI |
| `ibb_mcp` imports nothing from `nabiz`; import layers, no cycles, facade only, declared dependency sets | `scripts/check_architecture.py` (`layers`, `no-cycles`, `dependency-sets`), each shown red in `tests/test_check_architecture.py`; the server's import footprint in `tests/test_performance_budgets.py` | `make architecture`, `make test`, CI |
| Modules, classes and functions over budget never grow; one name, one meaning; no private imports | ruff C901, PLR0912, PLR0913, PLR0915; `scripts/check_architecture.py` (`module-size`, `class-size`, `complexity`, `one-meaning`, `private-imports`) against `scripts/architecture_baseline.json` | `make lint`, `make architecture`, CI |
| Upstream calls per tool (counted at the cache and at the boundary), single flight, stale-on-error, TTLs, parse once, cold-start imports, latency backstop | `tests/test_performance_budgets.py` (harness: `scripts/perf_report.py`) | `make perf-budgets`, `make test`, CI |
| Page bytes, blocking requests, fonts, motion (layout-free, reduced motion by structure, scripted motion only in `js/motion.js`), colour tokens, module sizes, icons, contract ids, no dash in the page's own text | `scripts/check_web_budget.py`; each check shown red in `tests/test_check_web_budget.py`; today's redesign targets in its `TARGETS_BY_CHECK`, where a met target must be deleted | `make web-budget`, CI |
| No dash in the text the server hands the page | `tests/test_answer_text.py` (every offline `/api/*` answer) | `make test`, CI |
| Web targets and architecture baseline entries are never raised or added quietly | **none**: nothing diffs `TARGETS_BY_CHECK` or `scripts/architecture_baseline.json` against the committed version; a raise carries its reason in the commit | review |
| Arrival estimates use the untuned rate unless `NABIZ_ETA_PROFILE_MODE=calibrated` (DECISIONS #18) | `tests/test_eta_profile.py` | `make test`, CI |
| Paths and `make` targets named in this file exist | guardrail `agent-rules-links` | `make guardrails`, CI |
| No secrets in tracked files | guardrail `no-secrets`; GitHub secret scanning + push protection | CI; on push |
| Every README §Results number is in the file its row names | guardrail `no-fabricated-metrics` (value by value) | `make guardrails`, CI |
| No user location server-side | `tests/test_alerts.py` (log capture, no-disk-write) | `make test`, CI |
| No personal e-mail or home path in tracked files | guardrail `no-personal-data` | `make guardrails`, CI |
| No hostname, hardware or subscription details | **none** | review |
| Edit only owned files; no agent git writes | **none** | review of the diff |
| Stop the line on red `main` | **none** until `main` is protected by a ruleset | owner |
| Sourced numbers outside README §Results | **none** | review |
| Optimisation claims carry before and after numbers | **none** | review |
| Web Vitals (LCP, INP, CLS) | **none in CI**: a Lighthouse run by hand, mobile preset, median of 3 | local |
