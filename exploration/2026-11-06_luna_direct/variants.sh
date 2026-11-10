#!/bin/zsh
# Codex Luna variants on the four control events where it fell furthest behind API Luna (15 calls per event).
R=${0:A:h:h:h}/data/interim; export S=$R/luna_direct
mkdir -p /tmp/lc
for v in rerun bare brief; do mkdir -p $S/variants/$v; done
for e in trump_statements_2025w10 drones_moscow_2025w11 putin_lukashenko_2025w11 mishustin_government_2020w03; do
  for p in $R/ten_events_readers/reader_labelling/prompts/${e}_*.txt; do print rerun $p; print bare $p; done
  for p in $R/ten_events_readers/reader_labelling/prompts_brief/${e}_*.txt; do print brief $p; done
done | xargs -P 16 -L 1 zsh -c '
  v=$1; p=$2; o=$S/variants/$v/${p:t:r}.json; [[ -s $o ]] && exit 0
  extra=(); [[ $v == bare ]] && extra=(-c model_instructions_file=\"$S/bare.md\")
  codex-secondary exec --skip-git-repo-check -C /tmp/lc -s read-only --ephemeral -m gpt-6-luna -c model_reasoning_effort=\"low\" $extra --output-schema $S/control/schema.json -o $o - < $p > /dev/null 2>&1
' _
