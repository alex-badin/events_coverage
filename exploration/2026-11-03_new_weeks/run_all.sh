#!/bin/zsh
# Drive the remaining events through briefs (Codex), Decisions and the Luna cut-off, round after
# round, while the cosine step is still producing candidates. Stops when every event has a cut-off
# or the budget in new_weeks.CAP_USD is spent (decide and luna refuse to go past it).
cd ${0:A:h}
P=../../.venv/bin/python
while true; do
  $P new_weeks.py brief_prompts
  zsh ../2026-10-17_jev_selection/codex_answer.sh ../../data/interim/new_weeks/briefs | tail -1
  $P new_weeks.py decide || true
  $P new_weeks.py luna || true
  done=$(ls ../../data/interim/new_weeks/luna | wc -l)
  over=$($P -c "import new_weeks as N; print(int(N.spent() >= N.CAP_USD - 0.1))")
  echo "$(date +%H:%M) $done events with a cut-off; spent $($P -c 'import new_weeks as N; print(round(N.spent(),2))')"
  (( done >= 870 || over )) && break
  sleep 60
done
