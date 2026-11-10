#!/bin/zsh
# One account: CODEX_CLI and workers as arguments. A stop at the limit waits 10 minutes and tries again.
cd ${0:A:h}
while true; do
  CODEX_CLI=$1 ../../.venv/bin/python luna_scores.py run --workers $2 && break
  echo "$(date +%H:%M) $1 stopped; waiting 10 minutes"
  sleep 600
done
echo "$(date +%H:%M) $1: nothing left to do"
