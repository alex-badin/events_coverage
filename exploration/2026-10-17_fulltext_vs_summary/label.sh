#!/bin/zsh
# Answer every labelling prompt of run.py with Codex (second account, subscription, no API spend).
# Usage: zsh label.sh [glob]   — glob limits the prompts, e.g. 'slice_kursk_2025w11_000*' for a trial.
# Reruns skip prompts that already have a valid answer.
set -u
ROOT=${0:A:h:h:h}
DIR=$ROOT/data/interim/fulltext_vs_summary/labels
GLOB=${1:-slice_*}
export CODEX_CLI=${CODEX_CLI:-codex-secondary}
export CODEX_MODEL=${CODEX_MODEL:-gpt-6.1-sol}
export PYTHON=$ROOT/.venv/bin/python DIR WORK=${TMPDIR:-/tmp}/fulltext_labelling
mkdir -p "$WORK" "$DIR/out" "$DIR/logs"

valid() { [[ -s "$1" ]] && "$PYTHON" -c 'import json, sys; assert isinstance(json.load(open(sys.argv[1]))["labels"], list)' "$1" 2>/dev/null }
todo=()
for p in "$DIR"/prompts/${~GLOB}.txt; do valid "$DIR/out/${p:t:r}.json" || todo+=$p; done
(( ${#todo} )) || { echo "nothing to do"; exit 0; }
echo "${#todo} prompts to answer with $CODEX_MODEL"
print -l $todo | xargs -P 6 -n 1 zsh -c '
  p=$1; name=${p:t:r}
  "$CODEX_CLI" exec --skip-git-repo-check -C "$WORK" -s read-only --ephemeral \
    -m "$CODEX_MODEL" -c model_reasoning_effort="medium" \
    --output-schema "$DIR/schema.json" -o "$DIR/out/$name.json" - < "$p" > "$DIR/logs/$name.log" 2>&1
  if [[ -s "$DIR/out/$name.json" ]]; then echo "$name answered"; echo "$CODEX_MODEL, medium, $("$CODEX_CLI" --version)" > "$DIR/out/$name.model"; else echo "$name FAILED"; fi
' _
