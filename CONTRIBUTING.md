# Contributing

İstanbul Nabız is a one-maintainer student project, and issues and pull requests are welcome. The rules
below are short because the reasoning lives elsewhere: [`docs/NABIZ.md`](docs/NABIZ.md) is the charter,
[`AGENTS.md`](AGENTS.md) binds AI coding agents, [`docs/ENGINEERING.md`](docs/ENGINEERING.md) explains why
each rule exists, and [`DECISIONS.md`](DECISIONS.md) records the choices that are expensive to reverse.
Security reports follow [`SECURITY.md`](SECURITY.md), not the issue tracker.

## Set up

```bash
uv venv -p 3.12 .venv       # Python 3.12, whatever the system python3 is
make install                # editable install with the dev and web extras, the same pair CI installs
export NABIZ_OFFLINE=1      # nothing you run while developing should reach İBB
make hooks                  # git push runs the authorship gate first (.githooks/pre-push)
```

`make hooks` matters because `main` is not protected yet: on a direct push, CI's authorship job can only
report a bad commit after it is public, and public history is permanent. The pre-push hook runs the same
check on the same range and refuses the push instead.

Every `make` target runs through `./.venv`, so a forgotten `activate` cannot test the wrong interpreter.
`make help` lists them all.

## Run the checks CI runs

| Command | What it checks | Blocks CI |
|---|---|---|
| `make lint` | `ruff check src/ scripts/ tests/ .github/scripts/` (line length 130) | yes |
| `make test` | the offline pytest suite; any network access fails the test | yes |
| `make smoke` | builds the MCP server offline: at least 12 tools, each with a real input schema | yes |
| `make guardrails` | `scripts/guardrails.py`: regression checks for incidents this repo already had | yes |
| `make authorship` | `scripts/check_authorship.py`: commit identity and message trailers | yes |
| `make eval` | the 30 journey scenarios against recorded fixtures; rewrites `eval/results/latest.md` (its `--selftest` runs inside `make test`) | not yet |
| `make ci-local` | the whole CI gate list in one command | — |
| `make fmt` | `ruff format` — advisory; CI only reports it | no |

Targets marked **NETWORK** in `make help` (`fixtures`, `eval-live`, `warmup`, `collect`, `collect-bg`,
`collect-supervise`) spend a request budget shared with every other user of İBB's gateway. Do not run them
in a loop, and never from a test.

## Making a change

- **One logical change per commit and per PR**, small enough to review in one sitting.
- **Tests with the change.** A new user-visible behaviour also needs a scenario in `eval/journeys.jsonl`.
- **Upstream access only through `PoliteClient`** (`src/ibb_mcp/http.py`) and the TTL cache. A new tool is
  parametric, returns a `ToolResult` with provenance, and in the same change gets its name in
  `EXPECTED_TOOLS` (`tests/test_mcp_integration.py`), a price in `TOOL_COSTS` (`src/ibb_mcp/server.py`), a
  scenario in `eval/journeys.jsonl` (the harness selftest fails without one), and either an entry in the
  agent's tool table or a line in `NOT_OFFERED` (`src/nabiz/agent/agent.py`). `make smoke` and the
  `mcp-schemas` guardrail only require at least 12 tools.
- **No personal data**, anywhere — including fixtures recorded from İBB, which are published with the code.
- **Numbers come from somewhere.** A figure in a doc or the README cites the file or command that produced it;
  what cannot be measured is written `n/a (reason)`.
- Docs describing the behaviour change in the same commit as the behaviour.

## Commit messages

Match the history (`git log --format='%s%n%n%b'`):

- An **imperative subject that says what changed and why it matters**, in plain English, e.g.
  *"Supervise the collector so data collection cannot silently stop"*. No type prefixes.
- A body wrapped at about 90 columns giving the reason: what broke or was missing, what was measured, what
  was deliberately not done.
- **No trailers.** In particular no `Co-Authored-By` for AI tools and no "Generated with" lines. You are the
  author and you answer for the change; an assistant is a tool, like an editor.

## Identity

Commit with your **GitHub noreply address** (GitHub → *Settings* → *Emails* → *Keep my email addresses
private*, then `git config user.email <id>+<login>@users.noreply.github.com`). The history of a public
repository is permanent, and a personal address committed once cannot be taken back without rewriting it.
The maintainer's own commits use `135648847+muratcan-ates@users.noreply.github.com`.

The authorship gate (`make authorship`, and the `authorship` job in CI) accepts **only the maintainer's
identity**, so a pull request from anyone else shows that job red, and `--reset-author` cannot turn it
green. That is expected: the other checks are the ones to get green. An accepted pull request is
re-committed by the maintainer under his own name, the same way a Dependabot bump is re-made rather than
merged ([`AGENTS.md`](AGENTS.md) §2).

## Licence

Code is MIT ([`LICENSE`](LICENSE)). İBB data is used under the İBB Açık Veri Lisansı (CC BY 4.0); keep the
attribution line wherever data is shown ([`NOTICE.md`](NOTICE.md)). This project is not affiliated with İBB,
İETT, İSPARK or Metro İstanbul, and nothing you add may suggest otherwise.
