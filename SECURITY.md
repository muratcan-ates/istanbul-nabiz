# Security policy

İstanbul Nabız is an unofficial student project: an MCP server and a city agent over İstanbul (İBB) open
data. It holds no user accounts and, by design, no personal data. Its security posture is mostly about three
things: not leaking what it should never have kept, not letting a client abuse the shared public gateway
behind it, and not letting untrusted text steer the agent.

## Supported versions

There are no releases yet. `ibb-mcp` is not published to PyPI and nothing is tagged, so **the latest commit on
`main` is the only supported version**. Fixes land on `main`; there are no backports.

## Reporting a vulnerability

**Please do not open a public issue with the details.**

Report privately through GitHub: the repository's **Security** tab → **Report a vulnerability** (private
vulnerability reporting). The report and the fix then live in one private advisory.

> **Owner action required:** private vulnerability reporting is switched **off** for this repository today
> (`GET /repos/muratcan-ates/istanbul-nabiz/private-vulnerability-reporting` returned `{"enabled":false}` on
> 2026-09-23). It is enabled under *Settings → Code security → Private vulnerability reporting*. Until it is,
> open a public issue titled "Security contact request" with **no details**, and a private channel will be
> set up with you from there.

A useful report names the affected module or endpoint, the commit, what an attacker gains, and the smallest
reproduction you have. Please do not test against İBB's own services (see *Out of scope*).

**What to expect:** an acknowledgement within 5 days and an assessment — a fix, or "won't fix, and why" —
within 30 days. This is a one-person student project, so that is a good-faith commitment, not an SLA. Please
allow that time before disclosing publicly; you will be credited in the advisory unless you prefer not to be.

## Scope

**In scope:**

- **The MCP server's public HTTP endpoint** (`ibb-mcp --transport http`, the shape Azure Container Apps runs)
  and the stdio server (`src/ibb_mcp/server.py`): tool argument handling, error paths, anything that makes
  a tool return data it should not, or return a number that is not in its source payload.
- **The web app and its API** (`src/nabiz/web/`), including `POST /api/alerts/check`.
- **Abuse of the shared upstream budget:** any request pattern that makes this project call İBB outside
  `PoliteClient` (`src/ibb_mcp/http.py`) or beyond its limits — at least 6 s between calls per host and 80
  İETT requests an hour, under İBB's documented 100 (DECISIONS #3).
- **Data handling:** a bus number plate surviving past the parser (`BusPosition.from_fleet_raw`, DECISIONS
  #7); a user coordinate reaching a log, a cache key or disk in the alert engine (`docs/privacy.md`); any
  personal data — including in recorded fixtures, which are published with the code.
- **Prompt injection through upstream data:** İBB free-text fields (stop names, disruption notices) reach the
  agent as data. Text that changes the agent's behaviour, or slips a number past the faithfulness check
  (`src/nabiz/agent/faithfulness.py`), is a finding.
- **Supply chain:** the GitHub Actions workflows in `.github/workflows/`, declared dependencies in
  `pyproject.toml`, and anything that would let a pull request run with more than a read-only token.
- **Secrets committed to the repository**, even revoked ones.

**Out of scope:**

- **İBB's own services** — `api.ibb.gov.tr`, `data.ibb.gov.tr` and the İETT, İSPARK and Metro İstanbul
  endpoints. This project does not operate them. Report issues there to İBB, and please do not probe them
  through this project: the gateway returns HTTP 503 to every consumer after about fifteen rapid requests.
- Volumetric denial of service against a scale-to-zero free-tier deployment.
- Findings that require already holding the deployment's environment variables or Azure credentials.
- Third-party platforms: Azure, GitHub, and whichever LLM endpoint an operator configures.
- The accuracy of İBB's data itself. Wrong or stale upstream data is a data-quality issue — an ordinary
  issue is the right place.

## Handling keys (owner)

The project needs almost none. İBB needs no key, Azure uses Entra sign-in and managed identities, and CI reads
no secret. Keys that can exist: `NABIZ_API_KEYS` (optional, the MCP HTTP edge), `NABIZ_LLM_API_KEY` or its
alias `LLM_API_KEY` (a keyed model endpoint only), and `NABIZ_MAPS_KEY`.

- The owner types a key himself, hidden: `read -rs NABIZ_LLM_API_KEY && export NABIZ_LLM_API_KEY`. Never as a
  literal on a command line, never pasted into an AI chat, never on screen in a recording.
- A key is checked as set or empty, never by value: `[ -n "${NABIZ_LLM_API_KEY:-}" ] && echo set || echo empty`.
- `NABIZ_MAPS_KEY` reaches every browser by design: treat it as public and restrict it on the Maps account.
- `NABIZ_API_KEYS` is empty by default, and the MCP edge stays keyless unless the owner decides otherwise. If it
  is adopted, it is declared in the template as a `@secure()` parameter so a provision cannot drop it. A secret
  set out of band with `az containerapp secret set` may be removed by the next `azd provision`; check with
  `az containerapp show -n "$APP" -g "$RG" --query "properties.configuration.secrets[].name"`.
- Rotate on leak: a key that appeared in a chat, a shared terminal, a screenshot or a video is revoked and
  replaced the same day. The date and the key's name, never its value, are recorded privately.
- Before the video and before delivery: `git log --all -p -S"$KEY" --format=%h | head -n 1` prints nothing,
  with the value taken from the environment.

## Posture (as of 2026-09-23)

Stated so a report can aim at the gaps rather than rediscover the defences. Update this table in the same
commit that closes a gap. Rows describe the working tree this file is committed with; nothing is
deployed yet.

| Area | What is in place | Known gap |
|---|---|---|
| Upstream protection | One shared `PoliteClient` and single-flight TTL cache; stale-on-error answers carry their age | budget lives in process, so the server is capped at one replica (`infra/modules/containerapps.bicep`) |
| HTTP endpoint | Public data only; tools are parametric (no free-form query, no URL argument); per-caller token bucket priced per tool, optional `X-API-Key`, closed CORS, 64 KiB body cap, length limits in every tool schema, stateless transport (`src/ibb_mcp/server.py`, `tests/test_server_security.py`); an unknown bus line is refused before it spends an İETT request (when the GTFS export is present) | per-client budgets are in process (one replica); the key is optional and off by default |
| Personal data | Plates dropped at parse, and the recorded fixtures carry synthetic ones; alert engine stateless, with tests asserting no coordinate reaches a log or disk; the web page sends a Content-Security-Policy and `Referrer-Policy: no-referrer` | guardrail `no-personal-data` covers e-mail and home paths; other machine details are review-only |
| Secrets | None needed to read İBB; `.env` ignored; guardrail `no-secrets`; GitHub secret scanning and push protection on | — |
| CI | `permissions: contents: read`; no workflow reads `secrets.*`; nothing deploys from CI; actions pinned to full commit SHAs and `uv` to its wheel hashes (`.github/requirements-uv.txt`); guardrails and the authorship gate run on every push | no dependency or code scanning yet; the pinned workflow has not run on GitHub yet |

The threat model — assets, trust boundaries and a STRIDE pass over the MCP surface — is
[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md). The engineering rules behind this table are in
[`docs/ENGINEERING.md`](docs/ENGINEERING.md) §7.
