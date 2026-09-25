#!/usr/bin/env bash
# Read-only snapshot for the start of a session, or after an interruption: branch and unpushed
# commits, dirty paths, a half-finished git operation, worktrees, the remote tip, recent CI runs,
# free disk, the collector, and which processes listen on the local ports. It writes nothing,
# changes no git state and calls no İBB host. `make status` runs it.
#
#   make status                                   # or: bash scripts/session_status.sh
#   STATUS_MIN_FREE_GB=10 make status             # the free-disk line warns below this
#
# The network reads (the remote tip, the gh login, the CI runs) go to GitHub only, each under a
# time limit and never to a prompt; a failure prints `not run: <reason>` instead of stopping the
# report. It always exits 0: it reports, it does not gate.
set -u
# `git status` refreshes the index when it can take the lock, which is a write, and in a tree
# another session is committing from it can collide with that session's own index lock.
export GIT_OPTIONAL_LOCKS=0

repo=$(git rev-parse --show-toplevel 2> /dev/null) || { echo "not a git checkout"; exit 0; }
cd "$repo" || exit 0
PY=${PY:-./.venv/bin/python}
MCP_PORT=${MCP_PORT:-8000}
WEB_PORT=${WEB_PORT:-8080}
STATUS_MIN_FREE_GB=${STATUS_MIN_FREE_GB:-5}
LIMIT_S=${STATUS_NETWORK_TIMEOUT_S:-20}

# macOS ships no `timeout`; perl's alarm is on both it and the Ubuntu runners.
limited() { perl -e 'alarm shift @ARGV; exec @ARGV or exit 127' "$LIMIT_S" "$@"; }
heading() { printf '\n== %s\n' "$1"; }

heading "branch"
git status -sb | head -1
echo "dirty paths: $(git status --porcelain | wc -l | tr -d ' ')"

heading "half-finished git operation"
gitdir=$(git rev-parse --git-dir)
pending=""
for marker in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD rebase-merge rebase-apply; do
  [ -e "$gitdir/$marker" ] && pending="$pending $marker"
done
if [ -n "$pending" ]; then
  echo "in progress:$pending; finish or abort it before anything else"
else
  echo "none"
fi

heading "worktrees"
git worktree list
git worktree list --porcelain | sed -n 's/^worktree //p' | while IFS= read -r path; do
  if [ -d "$path" ]; then
    echo "  $(git -C "$path" status --porcelain 2> /dev/null | wc -l | tr -d ' ') dirty path(s): $path"
  else
    echo "  missing on disk: $path"
  fi
done

heading "remote tip"
local_main=$(git rev-parse --verify -q main 2> /dev/null || echo "")
# No prompt: a passphrase or credential question would hang the report instead of failing it.
export GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes"
if remote=$(limited git ls-remote origin refs/heads/main 2> /dev/null) && [ -n "$remote" ]; then
  remote_main=${remote%%[[:space:]]*}
  if [ "$remote_main" = "$local_main" ]; then
    echo "origin/main = main ($local_main)"
  else
    echo "origin/main $remote_main != main ${local_main:-<none>}"
  fi
else
  echo "not run: git ls-remote origin failed or timed out after ${LIMIT_S}s"
fi

heading "CI on main"
if ! command -v gh > /dev/null; then
  echo "not run: gh is not installed"
elif ! limited gh auth status > /dev/null 2>&1; then
  echo "not run: gh is not logged in (gh auth status)"
elif ! limited gh run list --workflow ci.yml --branch main -L 3; then
  echo "not run: gh run list failed or timed out after ${LIMIT_S}s"
fi

heading "disk"
df -h .
free_kb=$(df -Pk . | awk 'NR == 2 {print $4}')
if [ -n "$free_kb" ] && [ "$free_kb" -lt $((STATUS_MIN_FREE_GB * 1024 * 1024)) ]; then
  echo "WARN: less than ${STATUS_MIN_FREE_GB} GB free; stop heavy work and ask the owner, delete nothing to free space"
fi

heading "collector"
pgrep -fl collect_forever.py || echo "no collect_forever.py process"
if [ -x "$PY" ]; then
  "$PY" scripts/collect_forever.py --status 2>&1 || echo "not run: collect_forever.py --status failed"
else
  echo "not run: $PY is missing"
fi

heading "listening on :$MCP_PORT and :$WEB_PORT"
lsof -nP -iTCP:"$MCP_PORT" -iTCP:"$WEB_PORT" -sTCP:LISTEN 2> /dev/null || echo "nothing"

exit 0
