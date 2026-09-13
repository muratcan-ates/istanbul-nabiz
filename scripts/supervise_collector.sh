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
while true; do
  echo "$(date '+%Y-%m-%d %H:%M:%S') supervisor: starting collector" >> logs/supervisor.log
  rm -f data/lake/.collector.lock
  caffeinate -is .venv/bin/python scripts/collect_forever.py >> logs/collector.log 2>&1
  code=$?
  echo "$(date '+%Y-%m-%d %H:%M:%S') supervisor: collector exited ($code), restarting in 30s" >> logs/supervisor.log
  sleep 30
done
