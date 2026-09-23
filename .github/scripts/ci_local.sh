#!/usr/bin/env bash
# Run .github/workflows/ci.yml locally, on a clean copy of exactly what a push would publish.
#
# "It passes on my machine" is how CI stayed red: in 10 of its first 13 runs, three tests
# read the gitignored data/reference/gtfs, which exists on a laptop and nowhere else. The
# suite in the working tree cannot catch that, so this copies only what git would publish
# (tracked files plus new files `git add` would pick up, never ignored ones) into a scratch
# directory, installs it into a fresh venv the way CI does, and runs the same gates.
#
#   make ci-local                                  # or: bash .github/scripts/ci_local.sh
#   CI_LOCAL_DIR=/some/scratch make ci-local       # where the copy lives (default: $TMPDIR)
#
# Offline: NABIZ_OFFLINE=1 and no İBB call anywhere. The venv survives between runs only
# while pyproject.toml, ci.yml and the uv pin are unchanged, which is CI's cache key; the
# tree is rebuilt every time. Every gate runs even after one fails, and the exit status is 1
# if any did. The Bicep job is not reproduced: it needs the az CLI.
set -uo pipefail

repo=$(git rev-parse --show-toplevel) || exit 2
dest=${CI_LOCAL_DIR:-"${TMPDIR:-/tmp}/istanbul-nabiz-ci-local"}
tree="$dest/tree"

# CI runs with a clean environment; a NABIZ_* override in this shell would not exist there.
while IFS= read -r name; do unset "$name"; done < <(env | sed -n 's/^\(NABIZ_[A-Za-z0-9_]*\)=.*/\1/p')
export NABIZ_OFFLINE=1 UV_HTTP_TIMEOUT=180

mkdir -p "$dest"
[ -d "$tree/.venv" ] && mv "$tree/.venv" "$dest/.venv.keep"
rm -rf "$tree" && mkdir -p "$tree"
[ -d "$dest/.venv.keep" ] && mv "$dest/.venv.keep" "$tree/.venv"

# -c also lists index entries whose file was deleted in the working tree; skip those. The list
# is kept: the copy has no git index, and the guardrails read it instead of walking the copy,
# whose walk skips directories such as logs/ that a still-tracked file can live in.
published="$dest/published.lst"
(cd "$repo" && git ls-files -co --exclude-standard -z) \
  | while IFS= read -r -d '' f; do [ -f "$repo/$f" ] && printf '%s\0' "$f"; done > "$published"
(cd "$repo" && tar --null -T "$published" -cf -) | tar -xf - -C "$tree"
echo "copied $(tr -cd '\0' < "$published" | wc -c | tr -d ' ') files into $tree"

cd "$tree" || exit 2
# CI installs the uv release pinned in .github/requirements-uv.txt; this uses the machine's
# own uv, so say so when the two differ: another uv may resolve the same ranges differently.
pinned_uv=$(sed -n 's/^uv==\([^ ]*\).*/\1/p' .github/requirements-uv.txt)
local_uv=$(uv --version | cut -d' ' -f2)
[ "$pinned_uv" = "$local_uv" ] || echo "note: CI installs uv $pinned_uv, this machine runs uv $local_uv"
# CI keys its venv cache on pyproject.toml, ci.yml and the uv pin with no restore-keys, so a
# dropped dependency fails there. `uv pip install` only ever adds, so a kept venv would hide
# that; rebuild it whenever the same three files change.
digest() { if command -v sha256sum > /dev/null; then sha256sum; else shasum -a 256; fi | cut -d' ' -f1; }
key=$(cat pyproject.toml .github/workflows/ci.yml .github/requirements-uv.txt | digest)
if [ "$(cat "$dest/venv.key" 2> /dev/null)" != "$key" ] || ! .venv/bin/python -c "" 2> /dev/null; then
  rm -rf .venv "$dest/venv.key"
  uv venv -q -p 3.12 .venv || exit 2
fi
uv pip install -q --python .venv/bin/python -e ".[dev,web]" || { echo "install FAILED"; exit 1; }
echo "$key" > "$dest/venv.key"

results=()
failed=0
gate() {
  local label=$1
  shift
  echo
  echo "=== $label"
  if "$@"; then
    results+=("PASS  $label")
  else
    results+=("FAIL  $label")
    failed=1
  fi
}

gate "ruff check" .venv/bin/ruff check src/ scripts/ tests/ .github/scripts/
echo
echo "=== ruff format --check (advisory, never fails)"
.venv/bin/ruff format --check src/ scripts/ tests/ | tail -1
gate "pytest" .venv/bin/python -m pytest -q --junitxml=reports/junit.xml
gate "ibb-mcp --help" sh -c '.venv/bin/ibb-mcp --help > /dev/null'
gate "MCP smoke test" .venv/bin/python .github/scripts/mcp_smoke.py
gate "guardrails" .venv/bin/python scripts/guardrails.py --files-from "$published"
# The copy has no history, so the authorship gate reads the real repository.
gate "authorship (@{upstream}..HEAD)" .venv/bin/python scripts/check_authorship.py --repo "$repo"

echo
echo "=== ci-local summary ($tree)"
printf '%s\n' "${results[@]}"
exit "$failed"
