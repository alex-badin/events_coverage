#!/bin/zsh
# Codex cut-offs for the scored events without one: second account, then the main one when its limit
# is hit, until every prompt has an answer or both accounts stop producing answers.
cd ${0:A:h}
D=../../data/interim/new_weeks/cutoffs
for cli in codex-secondary codex codex-secondary codex; do
  CODEX_CLI=$cli CODEX_MODEL=gpt-6.1-sol zsh ../2026-10-17_jev_selection/codex_answer.sh $D | grep -c answered
  echo "$(date +%H:%M) after $cli: $(ls $D/out | wc -l) of $(ls $D/prompts | wc -l)"
  [ $(ls $D/out | wc -l) -ge $(ls $D/prompts | wc -l) ] && break
done
echo FINISHED
