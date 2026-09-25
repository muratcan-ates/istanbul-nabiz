#!/usr/bin/env bash
# Run .github/workflows/ci.yml locally, on a clean copy of the tree.
#
# Two modes. `make ci-local` copies the working tree as `git add -A` would publish it: tracked files
# plus untracked ones that are not ignored. `make ci-commit` (CI_LOCAL_REF=HEAD) copies one commit
# exactly, with `git archive`: that is what a push publishes, whatever else in the tree is dirty.
#
# "It passes on my machine" is how CI stayed red: in 10 of its first 13 runs, three tests
# read the gitignored data/reference/gtfs, which exists on a laptop and nowhere else. The
# suite in the working tree cannot catch that, so this never copies an ignored file; it
# installs the copy into a fresh venv the way CI does, and runs the same gates.
#
#   make ci-local                                  # or: bash .github/scripts/ci_local.sh
#   make ci-commit                                 # or: CI_LOCAL_REF=HEAD bash .github/scripts/ci_local.sh
#   CI_LOCAL_DIR=/some/scratch make ci-local       # where the copy lives (default: $TMPDIR)
#   a second run on the same CI_LOCAL_DIR refuses to start (lock: $dest/.lock); give it another CI_LOCAL_DIR
#
# Offline: NABIZ_OFFLINE=1 and no İBB call anywhere. The venv survives between runs only
# while pyproject.toml, ci.yml and the uv pin are unchanged, which is CI's cache key; the
# tree is rebuilt every time. Every gate runs even after one fails, and the exit status is 1
# if any did. The Bicep job is not reproduced: it needs the az CLI.
set -uo pipefail

repo=$(git rev-parse --show-toplevel) || exit 2
dest=${CI_LOCAL_DIR:-"${TMPDIR:-/tmp}/istanbul-nabiz-ci-local"}
ref=${CI_LOCAL_REF:-}
tree="$dest/tree"
if [ -n "$ref" ]; then
  sha=$(git -C "$repo" rev-parse --verify -q "$ref^{commit}") || { echo "ci-local: $ref is not a commit"; exit 2; }
fi

# CI runs with a clean environment; a NABIZ_* override in this shell would not exist there.
while IFS= read -r name; do unset "$name"; done < <(env | sed -n 's/^\(NABIZ_[A-Za-z0-9_]*\)=.*/\1/p')
export NABIZ_OFFLINE=1 UV_HTTP_TIMEOUT=180

mkdir -p "$dest"
# One run per copy: a second run would delete the tree the first one is testing. A lock whose
# pid is gone, or now belongs to another program, is stale (the same rule as the collector's lock).
lock="$dest/.lock"
if ! mkdir "$lock" 2> /dev/null; then
  pid=$(cat "$lock/pid" 2> /dev/null)
  if [ -n "$pid" ] && ps -p "$pid" -o command= 2> /dev/null | grep -q ci_local.sh; then
    echo "ci-local: run $pid is using $dest; wait for it or set CI_LOCAL_DIR"
    exit 2
  fi
  rm -rf "$lock" && mkdir "$lock" || exit 2
fi
echo $$ > "$lock/pid"
trap 'rm -rf "$lock"' EXIT

[ -d "$tree/.venv" ] && mv "$tree/.venv" "$dest/.venv.keep"
rm -rf "$tree" && mkdir -p "$tree"
[ -d "$dest/.venv.keep" ] && mv "$dest/.venv.keep" "$tree/.venv"

# The list of copied files is kept: the copy has no git index, and the guardrails read it
# instead of walking the copy, whose walk skips directories such as logs/ that a still-tracked
# file can live in.
published="$dest/published.lst"
if [ -n "$ref" ]; then
  git -C "$repo" ls-tree -r -z --name-only "$sha" > "$published"
  git -C "$repo" archive "$sha" | tar -xf - -C "$tree"
  echo "copied $(tr -cd '\0' < "$published" | wc -c | tr -d ' ') files into $tree; tree = $ref $sha"
else
  # -c also lists index entries whose file was deleted in the working tree; skip those.
  (cd "$repo" && git ls-files -co --exclude-standard -z) \
    | while IFS= read -r -d '' f; do [ -f "$repo/$f" ] && printf '%s\0' "$f"; done > "$published"
  (cd "$repo" && tar --null -T "$published" -cf -) | tar -xf - -C "$tree"
  echo "copied $(tr -cd '\0' < "$published" | wc -c | tr -d ' ') files into $tree"
fi

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

gate "ruff check" .venv/bin/ruff check src/ scripts/ tests/ .github/scripts/ eval/
echo
echo "=== ruff format --check (advisory, never fails)"
.venv/bin/ruff format --check src/ scripts/ tests/ | tail -1
gate "pytest" .venv/bin/python -m pytest -q --junitxml=reports/junit.xml
gate "ibb-mcp --help" sh -c '.venv/bin/ibb-mcp --help > /dev/null'
gate "MCP smoke test" .venv/bin/python .github/scripts/mcp_smoke.py
gate "guardrails" .venv/bin/python scripts/guardrails.py --files-from "$published"
gate "architecture fences" .venv/bin/python scripts/check_architecture.py
gate "web budget" .venv/bin/python scripts/check_web_budget.py
# The copy has no history, so the authorship gate reads the real repository.
gate "authorship (@{upstream}..HEAD)" .venv/bin/python scripts/check_authorship.py --repo "$repo"

echo
echo "=== ci-local summary ($tree${ref:+, $ref = $sha})"
printf '%s\n' "${results[@]}"
exit "$failed"
