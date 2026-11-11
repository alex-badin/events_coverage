#!/bin/zsh
# History scores on one Codex account, newest events first. After a stop at the 5-hour window or the weekly cap
# (luna_scores.WEEK_CAP) it waits 10 minutes and tries again, until every event is scored.
cd ${0:A:h}
H=../../data/interim/history
while true; do
  find $H/scores -name "*.claim" -delete 2>/dev/null
  CODEX_CLI=$1 ../../.venv/bin/python history_scores.py run --workers ${2:-12} && break
  ../../.venv/bin/python history_scores.py status
  echo "$(date -u +%H:%M) $1 stopped; waiting 10 minutes"
  sleep 600
done
echo "$(date -u +%H:%M) every history event scored"
