#!/bin/zsh
# Answer prompt files with Codex (second account, subscription, no API spend).
# Usage: zsh codex_answer.sh <dir with prompts/ and schema.json> [glob]
# Reruns skip prompts that already have an answer.
set -u
DIR=${1:A}; GLOB=${2:-*}
export CODEX_CLI=${CODEX_CLI:-codex-secondary} CODEX_MODEL=${CODEX_MODEL:-gpt-6.1-sol}
export DIR WORK=${TMPDIR:-/tmp}/jev_selection_codex
mkdir -p "$WORK" "$DIR/out" "$DIR/logs"
todo=()
for p in "$DIR"/prompts/${~GLOB}.txt; do [[ -s "$DIR/out/${p:t:r}.json" ]] || todo+=$p; done
(( ${#todo} )) || { echo "nothing to do"; exit 0; }
echo "${#todo} prompts to answer with $CODEX_MODEL"
print -l $todo | xargs -P 6 -n 1 zsh -c '
  p=$1; name=${p:t:r}
  "$CODEX_CLI" exec --skip-git-repo-check -C "$WORK" -s read-only --ephemeral \
    -m "$CODEX_MODEL" -c model_reasoning_effort="medium" \
    --output-schema "$DIR/schema.json" -o "$DIR/out/$name.json" - < "$p" > "$DIR/logs/$name.log" 2>&1
  if [[ -s "$DIR/out/$name.json" ]]; then echo "$name answered"; else echo "$name FAILED"; fi
' _
