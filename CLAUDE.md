@AGENTS.md

## Claude Code

- `AGENTS.md` above is the whole rulebook; it is imported rather than copied so the two can never drift.
  Recent Claude Code versions also read `AGENTS.md` on their own; with this file present they read it through
  the import instead, once.
- `.claude/settings.json` turns attribution off for every session in this repository: `attribution.commit`
  and `attribution.pr` are empty strings, `attribution.sessionUrl` is `false`, and the deprecated
  `includeCoAuthoredBy: false` stays for CLI versions older than the `attribution` key. It sets nothing else.
- Personal overrides go in `.claude/settings.local.json`, which must stay untracked.
- A lane session never commits. The Integrator session commits only when the owner explicitly asks, after
  review, staging explicit paths (AGENTS.md §1). "Wrap it up" means suggested commits and a handoff.
