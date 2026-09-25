# `.github/workflows/`

One workflow, `ci.yml`, with three jobs. It runs on every push and pull request to `main`,
takes a couple of minutes, needs no Azure login and reads no secrets. The repository is
public and has none.

## What CI checks

| Job | Step | Gate? |
|---|---|---|
| `python` | uv from `.github/requirements-uv.txt` (`pip --require-hashes`), then `uv pip install -e ".[dev,web]"` on Python 3.12 | yes: a tampered uv wheel or a broken `pyproject.toml` fails here |
| | `ruff check src/ scripts/ tests/ .github/scripts/ eval/` | **yes** |
| | `ruff format --check --diff` | no, it only reports (see below) |
| | `pytest -q --junitxml=reports/junit.xml` | yes; the XML is uploaded as the `pytest-junit` artifact (14 days) |
| | MCP smoke test: `ibb-mcp --help`, then `.github/scripts/mcp_smoke.py` | yes |
| | `scripts/guardrails.py` | yes, on any FAIL; a WARN is printed but does not fail the build |
| | `scripts/check_architecture.py`: import layers, cycles, dependency sets, size and complexity ratchets | yes, on any FAIL; a WARN only says a baseline entry can be lowered |
| | `scripts/check_web_budget.py`: page bytes, render-blocking requests, fonts, motion, colour tokens, module sizes | yes, on any FAIL (a listed redesign target prints TARGET and passes until its step lands) |
| `authorship` | `scripts/check_authorship.py` over the pushed or proposed commits | **yes** |
| `bicep` | `az bicep build --file infra/main.bicep` (skipped if the file is absent) | yes |

The install is `.[dev,web]`, not `.[dev]`, because the suite needs `web`:
`tests/test_web.py` imports `fastapi.testclient` at module scope. With `[dev]` alone, pytest
aborts during collection (`Interrupted: 1 error during collection`, exit 2) and the whole step
goes red. The `collector` and `agent` extras are left out on purpose. Their tests install stub
modules in `sys.modules` and pass without the Azure and OpenAI wheels, and keeping those
wheels off the runner is what proves they still do.

**The MCP smoke test** builds the real server (`ibb_mcp.server.build_server()`) offline and
lists its tools. Each tool must advertise a JSON-schema object for its input, with its real
parameter names, never `args` or `kwargs`, plus a description. The script prints every tool
with its parameters. The tool count is a floor of 12, not an exact number: adding a tool is a
feature, losing one is the incident, and `tests/test_mcp_integration.py` pins the exact names.
The test suite does not cover this. The tests call the tool functions directly. Only a
server build shows a tool that fails to *register*: a signature the SDK cannot turn into a
schema, an import error, or the `@tool` wrapper losing `functools.wraps`, which once made
every tool advertise `(*args, **kwargs)`. `ibb-mcp --help` proves the console script that
the `uvx ibb-mcp` instructions depend on was installed.

**The guardrails** (`scripts/guardrails.py --list`) are regression fences for incidents this
project has already had:

- `no-plate`: a number plate read past the parser.
- `fixture-plates-synthetic`: a fixture plate not starting with `00 `, or a plate-shaped example
  with a real province code anywhere else in the tree.
- `mcp-schemas`: the tool schemas.
- `no-raw-ibb-calls`: an İBB call that bypasses `PoliteClient`.
- `csv-truncation`: a GTFS export cut off at Excel's row limit.
- `coordinate-sanity`: a coordinate outside İstanbul.
- `no-secrets`: a credential in a tracked file.
- `no-personal-data`: an e-mail address other than the two noreply ones, or a home-directory
  path, in a tracked file.
- `no-ai-attribution`: a `Co-Authored-By` or "Generated with <assistant>" line in a tracked file.
- `fixture-freshness`: stale recorded İBB responses. This one only warns.
- `no-fabricated-metrics`: a number in README §Results that the `eval/results/` or `data/reference/`
  file named in its row does not hold.
- `agent-rules-links`: a repository path or `make` target named in `AGENTS.md`, `CLAUDE.md` or
  `CONTRIBUTING.md` that does not exist, or a relative link in any tracked Markdown file that does
  not resolve.
- `no-azure-ids`: a subscription, tenant or client id pasted into a tracked file.

They need no network and no git history. Every exception is listed in the script with its
reason. The smoke test and the guardrails also run when lint or tests have failed, so one
push reports every broken gate at once.

**The architecture fences** (`scripts/check_architecture.py`, docs/ENGINEERING.md §13) fence the
*shape* of the code: `ibb_mcp` imports nothing from `nabiz` (DECISIONS #8, #19), every import points down
the layer stack, no cycle, no third-party import outside the package's declared set, one definition per
public name, no private imports, and ratchets on module size, class size and ruff's complexity rules
against `scripts/architecture_baseline.json`. Measured debt may shrink, never grow past its entry;
`make architecture-tighten` records a shrink, and raising an entry is a reviewed change the gate cannot
see. The complexity check re-runs ruff `--isolated` with its own thresholds, `--ignore-noqa` and without
the debt ignores in `pyproject.toml`, so neither a `# noqa` nor a loosened `pyproject.toml` can hide a
function getting worse. The performance budgets
(`tests/test_performance_budgets.py`, §14) need no step of their own: they run inside the pytest step.

**The web budget** (`scripts/check_web_budget.py`, FE-MOD and FE-OPT in docs/design/DESIGN.md) reads
`src/nabiz/web/static` and needs no network. The page did not meet every rule on the day the gate landed,
so the findings it had are listed in the script's `TARGETS_BY_CHECK`, each with the redesign step that
removes it and, for a count, the count it may not exceed. The step fails on any finding not in that table,
on a count above its target, and on a target that was met but is still listed, so each redesign step
deletes what it fixed; raising or adding an entry is a reviewed change the step cannot see. When the
table is empty, the step switches to `--strict` (docs/design/README.md).

`NABIZ_OFFLINE=1` is set for the whole workflow. **CI never calls `api.ibb.gov.tr`.** That
gateway is shared public infrastructure. It returns 503 after roughly fifteen rapid calls,
and the İETT service documents 100 requests/hour for everyone. A test suite that spent that
budget on every push would be rude and flaky in equal measure, so every source reads
recorded fixtures instead.

The `bicep` job compiles `infra/main.bicep`, which transitively compiles every module
`main.bicep` references. The step is guarded with `if: hashFiles('infra/main.bicep') != ''`,
so the workflow also works on a branch or a point in history where the template does not
exist yet: it reports "nothing to compile" instead of failing. The guard has to sit on the
*step*, not the job. At job level, `hashFiles` is evaluated before `actions/checkout` has
populated the workspace, so it would always be false. `az bicep build` is a local compile
that needs no subscription, login or secret. When it runs it is a hard gate: a module file
that is referenced but missing, or a template that does not type-check, is a real error and
stops the build.

## Why CI was red, and how the fix stays fixed

Every one of the first 13 runs failed (`gh run list`, checked 2026-09-23). Three failed at
`ruff check`. The other ten failed on the same three `tests/test_web.py` tests: stop search,
arrival estimate and off-route refusal. Those tests need GTFS, and `data/reference/gtfs/`
(about 180 MB) is gitignored. They passed on the laptop that has the files and failed on
every runner.

The fix is data, not a skip. `tests/fixtures/gtfs_mini/` is a 38 KB cut of İBB's real export.
Its README documents the source, the date and the CC BY 4.0 attribution, and `extract.py`
regenerates it. `tests/conftest.py` points its shared offline settings (the `settings` and
`ctx` fixtures, and `offline_settings()`) at a per-session copy of that fixture, so a test
built on them cannot read the gitignored export. A test that constructs `Settings()` by
hand still can, and `make ci-local` is what catches that. The fixture keeps a real
off-route case: 500T runs Şifa Sondurak ↔ 4.Levent Metro and never serves Kadıköy.

The general lesson: a check that passes in the working tree proves nothing about CI.
**`make ci-local`** copies the working tree as `git add -A` would publish it (tracked files plus
new files `git add` would pick up, never ignored ones) into a scratch directory, installs it into a
fresh venv the way CI does, and runs every gate. **`make ci-commit`** does the same for `HEAD`
exactly as committed (`git archive`), which is what a push publishes, whatever else in the tree is
dirty. One run per scratch directory: a second run on the same `CI_LOCAL_DIR` refuses to start. The venv is kept between runs only while
`pyproject.toml`, `ci.yml` and `.github/requirements-uv.txt` are unchanged, which is CI's own
cache key, so a dropped dependency fails locally too. It uses the machine's uv and prints a
note when that is not the release CI pins. The copy has no git index, so the guardrails read the same
published list (`--files-from`) instead of walking the copy. See `.github/scripts/ci_local.sh`.

## Running the same checks locally

```bash
make install    # uv pip install -e ".[dev,web]"               — the extras CI installs
make lint       # ruff check src/ scripts/ tests/ .github/scripts/ eval/ — the gate
make test       # pytest -q                                     — must be green
make smoke      # the MCP smoke test CI runs
make guardrails # scripts/guardrails.py
make architecture   # scripts/check_architecture.py — import layers and size ratchets
make web-budget     # scripts/check_web_budget.py — the page's byte, font, motion and token budget
make perf-budgets   # tests/test_performance_budgets.py — already part of make test
make authorship # scripts/check_authorship.py on @{upstream}..HEAD — run before pushing
make ci-local   # all of the above on a clean copy of the working tree (CI_LOCAL_DIR= to choose where)
make ci-commit  # the same on HEAD exactly as committed: what a push publishes
make fmt        # ruff format (advisory; CI only reports it)
```

`make help` lists every target. The Bicep step, once there is something to compile:

```bash
az bicep build --file infra/main.bicep --stdout > /dev/null
```

## The authorship gate

AGENTS.md §2: the owner is the author of every commit, under
`135648847+muratcan-ates@users.noreply.github.com`, with no AI credit and no bot identity.
`scripts/check_authorship.py` fails a commit when:

- its author e-mail is not that address, or its committer e-mail is neither that address nor
  `noreply@github.com` (GitHub's own committer for merges made in the web UI);
- its author or committer name names an assistant or a bot, from the same list the message
  rules use: `claude`, `anthropic`, `chatgpt`, `openai`, `gpt`, `copilot`, `codex`, and the whole
  words `gemini`, `cursor`, `aider` and `ai`, plus `[bot]` and `dependabot` (case-insensitive).
  Aider keeps the configured e-mail and appends ` (aider)` to the name, so the e-mail rule alone
  would not catch it;
- its message has a `Co-Authored-By:` line, a "Generated with/by <assistant>" line, aider's
  `aider:` subject prefix, a crediting trailer (`<verb>-by:`, `<verb>-with:`, `<tool>-session:`,
  `AI-…:`) in the closing paragraph that names an assistant, or the robot emoji those footers
  carry. A closing line such as `Tested: VS Code Copilot lists the tools` is prose, not a credit.

Prose about the rule passes. A subject such as "Reject Co-Authored-By trailers" is not a
trailer, so the commit that adds this gate can describe it.

A commit made in the GitHub web UI (a merge, a squash, an edit) gets GitHub as committer and
the account's *commit e-mail* as author. It passes only while *Settings → Emails → Keep my
email addresses private* is on, because that setting makes the commit e-mail the noreply
address. The repository's first commit (`9915a02`, created on GitHub) shows the setting was
on when the repository was created.

**Which commits.** Only the new ones, never the whole history:

| Event | Range checked |
|---|---|
| `pull_request` | `base.sha..head.sha`: the commits the PR proposes |
| `push` | `before..after`: what the push added. After a force-push this is every rewritten commit |
| `push` that created the branch (`before` is all zeros) | the pushed tip only, with a notice in the log |
| force-push whose old tip is gone | CI first fetches the old tip by SHA (GitHub serves it until garbage collection). If that fails, it checks the pushed tip only and posts a warning |

The job checks out with `fetch-depth: 0`, because a shallow clone holds one commit and the
range could not be walked.

**Why not the whole history.** 19 of the first 21 commits on `main` have
the owner's personal address as author and committer. The other two already use the noreply
address. History on a public repository is permanent. Rewriting it changes every SHA,
breaks every clone and every link to a commit, and needs a force-push. That is the owner's
decision, not CI's. A gate that failed on those commits would fail every push until then, so
it checks only what is new. If the owner rewrites (for example `git filter-repo --mailmap`,
then a force-push), the gate checks every rewritten commit on that push, which confirms the
rewrite is complete. The address is not repeated here on purpose.

## Supply chain

- **Every third-party action is pinned to a full commit SHA**, with the release in a comment:
  `actions/checkout` v5.1.0, `actions/setup-python` v6.3.0, `actions/cache` v5.1.0 and
  `actions/upload-artifact` v6.0.0. A tag can be moved to different code at any time; a SHA
  cannot. These are the first major versions of each action that run on Node 24. The
  previous `@v4`/`@v5` tags targeted Node 20, and the runner was already forcing them onto
  Node 24 with a deprecation warning on every run. The release notes for all four list the
  runtime as the only breaking change. To bump one, look up the new SHA with
  `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` and update the comment with it.
- **The pinning is a convention, not a setting yet.** The repository's Actions policy allows
  any action and does not require SHA pins (`gh api repos/muratcan-ates/istanbul-nabiz/actions/permissions`
  on 2026-09-23: `"allowed_actions":"all"`, `"sha_pinning_required":false`), so a future
  `uses: x@v1`, or a marketplace action that commits or opens pull requests as a bot, would run
  without complaint. **Owner action:** *Settings → Actions → General* → *Require actions to be
  pinned to a full-length commit SHA*, and allowed actions → *GitHub-authored actions* (all four
  in use are `actions/*`).
- **uv is pinned by version and by hash.** `.github/requirements-uv.txt` names uv 0.11.14 and
  the SHA-256 of each of its 18 wheels on PyPI, and the job installs it with
  `python -m pip install --no-deps --only-binary :all: --require-hashes -r .github/requirements-uv.txt`.
  A wheel whose bytes differ from the committed hash fails the install instead of running, and
  a new uv release cannot change dependency resolution between two pushes of the same
  `pyproject.toml`. This replaced `curl https://astral.sh/uv/<version>/install.sh | sh`, which
  ran whatever script that URL served, unchecked. `astral-sh/setup-uv` pinned to a SHA would
  also have closed that, but it is a third-party action, and CI stays on GitHub-authored
  actions so the policy above can be switched on without breaking it. Checked on 2026-09-23 on
  a laptop, not yet on a runner: the command installs uv 0.11.14 into a fresh Python 3.12
  venv, and the same file with one hash changed is refused ("THESE PACKAGES DO NOT MATCH THE
  HASHES"). The venv cache key includes the file, so a bump rebuilds the venv. To bump, copy
  the version and every `bdist_wheel` sha256 from `https://pypi.org/pypi/uv/<version>/json`.
- **No Dependabot version updates, on purpose.** A `dependabot.yml` makes `dependabot[bot]`
  open pull requests under its own name. That puts a bot in the contributor list, and the
  authorship gate would reject its commits anyway. The owner can still turn on **Dependabot
  alerts** under *Settings → Code security*. Alerts only notify: they open no PR and make no
  commit. Leave *Dependabot security updates* off, because that setting opens bot PRs. When an
  alert fires, the owner makes the bump himself, under his own name.
- **No OpenSSF Scorecard workflow yet.** Publishing its results needs `id-token: write` and
  `security-events: write`, which would widen a token that is `contents: read` everywhere
  today. An unpublished run adds a job whose output nobody reads. If the owner wants the
  badge, add it as a separate, advisory, SHA-pinned workflow on a weekly schedule, not on
  every push.

## Why `ruff format` does not fail the build

`ruff format --check src/ scripts/ tests/` would reformat 42 files and leave 30 as they are,
measured on 2026-09-23 with `make ci-local`. The number changes with every file that lands,
so re-run the command rather than trust it. Almost every change is the same disagreement:
`line-length` is 130, the source wraps long expressions by hand across several lines for
readability, and the formatter joins them back into one 130-character line. That is a style
preference, not a defect. Enforcing it mid-sprint would produce a large mechanical diff that
buries real changes in review.

So the split is deliberate: **`ruff check` (E, F, I, UP, B, SIM, and the size rules C90, PLR0912,
PLR0913, PLR0915) is the gate, and formatting is advisory.** The diff is printed in the job log with `continue-on-error: true`, so the drift
stays visible without blocking the build. After the feature freeze, the plan is one
formatting-only commit, then turning `continue-on-error` off. That is a one-line change in
`ci.yml` and a one-line change here.

## Why CI does not deploy — yet

Deployment is `azd up` / `azd deploy` **from a laptop**. This is a decision, not an omission.

A deploy job needs credentials for the Azure subscription. In a public repository there are
two honest ways to get them, and neither is available today:

- **A long-lived client secret in repository secrets.** Rejected. A student subscription
  credential sitting in a public repo's settings, in a project whose whole point is a
  publicly readable open-data server, is the wrong risk to take to save one terminal command.
- **OIDC federated credentials** (`permissions: id-token: write` plus `azure/login` with no
  secret). This is the right answer. It needs an **app registration plus a federated identity
  credential on the tenant that owns the subscription**. Nobody has confirmed that this
  university tenant allows app registration. PLAN §15 carries it as a live risk, and
  DECISIONS #1 already makes the Azure Data Explorer choice depend on the *same* open tenant
  question. A deploy workflow written against an unconfirmed capability would never have run
  successfully, which is worse than having none.

CI therefore does the part a runner can do honestly without a login: install the project,
lint it, test it, prove the server starts, and compile the infrastructure templates.

When app registration is confirmed to work, add `deploy.yml` with:

- `permissions: { id-token: write, contents: read }` and `azure/login` using **variables**
  (`vars.AZURE_CLIENT_ID`, `vars.AZURE_TENANT_ID`, `vars.AZURE_SUBSCRIPTION_ID`), since client
  and tenant ids are public GUIDs, not secrets, and no client secret anywhere;
- a `workflow_dispatch` trigger and a GitHub `environment:` gate, so a merge to `main` can
  never deploy by accident;
- `azd deploy` only. `azd provision` stays manual, because it is the step that can create
  billable resources.

`publish.yml` (PyPI trusted publishing for `ibb-mcp`) is on the same stretch list and has the
same shape: an OIDC identity instead of an API token.

## Housekeeping

- **No workflow here reads a secret.** `grep -rn '\${{ *secrets\.' .github/` returns nothing.
  The word "secrets" appears only in prose, including this line. Keep it that way.
- Event fields reach shell code only through `env:`, never as `${{ }}` inside `run:`. The
  authorship job does this for its SHAs, so no event field is ever pasted into a script.
- Two caches: `~/.cache/uv` holds wheels, keyed on `pyproject.toml` with a prefix
  `restore-keys` fallback. `.venv` uses an exact key only, built from `pyproject.toml`, **`ci.yml`
  and `.github/requirements-uv.txt`**. The extras list lives in the workflow, so editing it has
  to invalidate the venv, and another uv release may resolve the same ranges differently.
  A venv restored against a different dependency set would install on top of stale wheels and
  hide exactly the breakage this job exists to catch.
- `concurrency` cancels superseded runs on the same ref, and every job's token is
  `contents: read`.
