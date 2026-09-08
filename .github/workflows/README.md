# `.github/workflows/`

One workflow, `ci.yml`. It runs on every push and pull request to `main`, takes a couple of
minutes, needs no Azure login and reads no secrets — the repository is public and has none.

## What CI checks

| Job | Step | Gate? |
|---|---|---|
| `python` | `uv pip install -e ".[dev,web]"` on Python 3.12 | yes — a broken `pyproject.toml` fails here |
| | `ruff check src/ scripts/ tests/` | **yes** |
| | `ruff format --check --diff` | no — reported only, see below |
| | `pytest -q --junitxml=reports/junit.xml` | yes; the XML is uploaded as the `pytest-junit` artifact (14 days) |
| | MCP smoke test: build the real server, assert it lists **12** tools | yes |
| `bicep` | `az bicep build --file infra/main.bicep` (skipped if the file is absent) | yes |

The install is `.[dev,web]`, not `.[dev]`. That is not tidiness: `tests/test_web.py` imports
`fastapi.testclient` at module scope, so a `[dev]`-only environment makes pytest abort during
collection (`Interrupted: 1 error during collection`, exit 2) and the whole step goes red. The
`collector` and `agent` extras are deliberately left out — those tests install stub modules in
`sys.modules` and pass without the Azure and OpenAI wheels, and keeping the wheels off the
runner is what keeps that true.

The smoke test is not redundant with the test suite. The tests exercise the tool layer
directly; the smoke test builds `ibb_mcp.server.build_server()` and calls `list_tools()`, so
a tool that fails to *register* — a signature the MCP SDK cannot turn into a JSON schema, an
import error, a decorator applied in the wrong order — fails CI instead of failing silently
inside someone's editor. It also runs `ibb-mcp --help`, which proves the console script the
`uvx ibb-mcp` install instructions depend on actually got installed.

`NABIZ_OFFLINE=1` is set for the whole workflow. **CI never calls `api.ibb.gov.tr`.** That
gateway is shared public infrastructure that 503s after roughly fifteen rapid calls, and the
İETT service documents 100 requests/hour for everyone. A test suite that spends that budget
on every push would be rude and flaky in equal measure, so every source reads recorded
fixtures instead.

The `bicep` job compiles `infra/main.bicep`, which transitively compiles every module
`main.bicep` references. The step is guarded with `if: hashFiles('infra/main.bicep') != ''`
so the workflow is also correct on a branch or a point in history where the template does
not exist yet — it reports "nothing to compile" instead of failing. The guard has to sit on
the *step*, not the job: at job level `hashFiles` is evaluated before `actions/checkout` has
populated the workspace, so it would be false forever. `az bicep build` is a local compile
needing no subscription, no login and no secret, so when it runs it is a hard gate — a
module file that is referenced but missing, or a template that does not type-check, is a
real error and stops the build.

## Running the same checks locally

```bash
make install # uv pip install -e ".[dev,web]"       — the extras CI installs
make lint    # ruff check src/ scripts/ tests/      — the gate
make test    # pytest -q                            — must be green; count moves daily
make smoke   # build the MCP server offline, assert 12 tools
make fmt     # ruff format (advisory; CI only reports it)
```

`make help` lists every target. The Bicep step, once there is something to compile:

```bash
az bicep build --file infra/main.bicep --stdout > /dev/null
```

## Why `ruff format` does not fail the build

`ruff format --check src/ scripts/ tests/` reformats most of the tree — 21 of 39 files when
this was last measured, on 2026-09-08, but re-run the command rather than trusting that
number, it moves with every file that lands. Almost every hunk is the same disagreement:
`line-length` is 130, the source hand-wraps long expressions across several lines for
readability, and the formatter joins them back into one 130-character line. That is a style
preference, not a defect, and enforcing it mid-sprint would produce a large mechanical diff
that buries real changes in review.

So the split is deliberate: **`ruff check` (E, F, I, UP, B, SIM) is the gate; formatting is
advisory.** The diff is printed in the job log, `continue-on-error: true`, so the drift stays
visible without blocking. After the Sunday feature freeze the intended fix is one
formatting-only commit followed by flipping `continue-on-error` off — a one-line change in
`ci.yml` and a one-line change here.

## Why CI does not deploy — yet

Deployment is `azd up` / `azd deploy` **from a laptop**. This is a decision, not an omission.

A deploy job needs credentials for the Azure subscription. In a public repository there are
two honest ways to get them, and neither is available today:

- **A long-lived client secret in repository secrets.** Rejected. A student subscription
  credential sitting in a public repo's settings, in a project whose whole point is a
  publicly readable open-data server, is the wrong risk to take for saving one terminal
  command.
- **OIDC federated credentials** (`permissions: id-token: write` + `azure/login` with no
  secret) — the right answer, and it requires an **app registration plus a federated
  identity credential on the tenant that owns the subscription**. Whether this university
  tenant permits app registration is unverified; PLAN §15 carries it as a live risk, and
  DECISIONS #1 already gates the Azure Data Explorer choice on the *same* unanswered
  tenant-permission question. Writing a deploy workflow against a capability nobody has
  confirmed produces a workflow that has never successfully run, which is worse than not
  having one.

CI therefore does the part a runner can do truthfully with no login: install the project,
lint it, test it, prove the server starts, and compile the infrastructure templates.

When app registration is confirmed to work, add `deploy.yml` with:

- `permissions: { id-token: write, contents: read }` and `azure/login` using **variables**
  (`vars.AZURE_CLIENT_ID`, `vars.AZURE_TENANT_ID`, `vars.AZURE_SUBSCRIPTION_ID`) — client and
  tenant ids are public GUIDs, not secrets — and no client secret anywhere;
- a `workflow_dispatch` trigger and a GitHub `environment:` gate, so merging to `main` can
  never deploy by accident during a seven-day sprint;
- `azd deploy` only. `azd provision` stays manual: it is the step that can create billable
  resources.

`publish.yml` (PyPI trusted publishing for `ibb-mcp`) is on the same stretch list, and has
the same shape — an OIDC identity instead of an API token.

## Housekeeping

- **No workflow here reads a secret.** `grep -rn '\${{ *secrets\.' .github/` returns
  nothing (the word "secrets" appears only in prose, including this line); keep it that way.
- `uv` is installed from the official `astral.sh` installer, unpinned. Two caches:
  `~/.cache/uv` (wheels, keyed on `pyproject.toml`, with a prefix `restore-keys` fallback)
  and `.venv` (exact key only, keyed on `pyproject.toml` **and `ci.yml`** — the extras list
  lives in the workflow, so editing it has to invalidate the venv; and a venv restored
  against a different dependency set would install on top of stale wheels and hide exactly
  the breakage this job exists to catch).
- `concurrency` cancels superseded runs on the same ref, and the token is `contents: read`.
