#!/bin/bash
# Keep the collector alive.
#
# Two earlier runs died silently: the first when the machine slept, the second when its
# parent shell went away. The history İBB does not publish only accumulates while this is
# running, so an unsupervised collector is a data-loss bug, not an inconvenience.
#
# launchd would be the macOS-native answer, but a user LaunchAgent needs a TCC grant this
# session cannot give, so the job stalls in xpcproxy without ever exec'ing. This supervisor
# needs no permissions: caffeinate holds off sleep, the loop restarts on any exit, and the
# pid lock inside collect_forever.py still prevents two collectors racing.
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs data/lake

# One supervisor at a time. An earlier version deleted the collector's pid lock before
# every start, so running `make collect-supervise` twice produced two collectors racing
# the same İETT hourly budget. The collector already recognises a stale lock by checking
# whether the pid in it is alive, so the supervisor must never delete it.
#
# A lock is live only while its pid is alive AND that process started when the lock says it
# did. After a crash, a kill -9 or a power cut the trap below never runs, and after a reboot
# the stale pid can belong to an unrelated process: `kill -0` alone would then refuse to
# start and keep the collector down until someone noticed. A one-line lock from the version
# before this falls back to `kill -0`, so it never lets two supervisors run side by side.
SUP_LOCK=data/lake/.supervisor.pid
started() { ps -o lstart= -p "$1" 2>/dev/null; }
if [ -f "$SUP_LOCK" ]; then
  old_pid='' old_start=''
  { IFS= read -r old_pid; IFS= read -r old_start; } < "$SUP_LOCK"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null \
    && { [ -z "$old_start" ] || [ "$(started "$old_pid")" = "$old_start" ]; }; then
    echo "supervisor already running as pid $old_pid" >&2
    exit 1
  fi
fi
printf '%s\n%s\n' "$$" "$(started $$)" > "$SUP_LOCK"
trap 'rm -f "$SUP_LOCK"' EXIT

while true; do
  echo "$(date '+%Y-%m-%d %H:%M:%S') supervisor: starting collector" >> logs/supervisor.log
  caffeinate -is .venv/bin/python scripts/collect_forever.py >> logs/collector.log 2>&1
  code=$?
  echo "$(date '+%Y-%m-%d %H:%M:%S') supervisor: collector exited ($code), restarting in 30s" >> logs/supervisor.log
  sleep 30
done
