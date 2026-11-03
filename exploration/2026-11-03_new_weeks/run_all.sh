#!/bin/zsh
# Drive the remaining events through briefs (Codex), Decisions and the Luna cut-off, round after
# round, while the cosine step is still producing candidates. Stops when every event has a cut-off
# or a round adds none (the budget in new_weeks.CAP_USD is used up, or the API refuses).
cd ${0:A:h}
P=../../.venv/bin/python
prev=-1
while true; do
  $P new_weeks.py brief_prompts
  CODEX_CLI=${CODEX_CLI:-codex} zsh ../2026-10-17_jev_selection/codex_answer.sh ../../data/interim/new_weeks/briefs | tail -1
  $P new_weeks.py luna || true    # first the events already scored: a score without a cut-off is wasted
  $P new_weeks.py decide || true
  $P new_weeks.py luna || true
  done=$(ls ../../data/interim/new_weeks/luna | wc -l)
  echo "$(date +%H:%M) $done events with a cut-off; spent $($P -c 'import new_weeks as N; print(round(N.spent(),2))')"
  (( done >= 870 || done == prev )) && break
  prev=$done
  sleep 60
done
