#!/bin/zsh
# Codex Luna on the stored prompts of the ten control events (150 calls, 50 posts each), same files API Luna got.
C=${0:A:h:h:h}/data/interim/luna_direct/control
P=${0:A:h:h:h}/data/interim/ten_events_readers/reader_labelling/prompts
export C
mkdir -p /tmp/luna_control
ls $P/*.txt | xargs -P 8 -n 1 zsh -c '
  p=$1; n=${p:t:r}; [[ -s $C/out/$n.json ]] && exit 0
  codex-secondary exec --skip-git-repo-check -C /tmp/luna_control -s read-only --ephemeral -m gpt-6-luna -c model_reasoning_effort=\"low\" --output-schema $C/schema.json -o $C/out/$n.json - < $p > $C/logs/$n.log 2>&1
' _
