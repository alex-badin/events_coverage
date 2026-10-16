#!/bin/zsh
# Answer every prompt of the newest labelling run (or the run folder given as $1) with Codex,
# six calls at a time.
#
# One pinned model for every prompt, so label differences between periods cannot come from a
# model difference; change CODEX_MODEL only on purpose. Each answer gets a .model file next to
# it saying which model and CLI version produced it, and the seed copies that into
# labelled_by. Codex runs read-only from an empty folder: each prompt carries everything it
# needs. Uses the Codex subscription, not paid API calls.
#
# A prompt that already has a valid answer is skipped, so a failed run can simply be
# repeated. An answer that is not valid JSON is moved aside as <slice>.bad. The script exits
# with an error while any prompt of the run is still without a valid answer.
#
#   zsh scripts/run_theme_labelling.sh                     # second account (codex-secondary)
#   CODEX_CLI=codex zsh scripts/run_theme_labelling.sh     # main account
set -eu
ROOT=${0:A:h:h}
RUN=${1:-$(ls -d "$ROOT"/data/interim/themes/labels/*/ 2>/dev/null | sort | tail -1)}
RUN=${RUN%/}
[[ -d "$RUN/prompts" ]] || { echo "No labelling run found; run scripts/fom_themes.py prompts first." >&2; exit 1; }
export CODEX_CLI=${CODEX_CLI:-codex-secondary}
export CODEX_MODEL=${CODEX_MODEL:-gpt-6.1-sol}
export PYTHON=$ROOT/.venv/bin/python
export RUN WORK=${TMPDIR:-/tmp}/fom_theme_labelling
mkdir -p "$WORK" "$RUN/out" "$RUN/logs"

valid() {  # is $1 an answer file with a list of labels?
  [[ -s "$1" ]] && "$PYTHON" -c 'import json, sys; assert isinstance(json.load(open(sys.argv[1]))["labels"], list)' "$1" 2>/dev/null
}

todo=()
for p in "$RUN"/prompts/slice_*.txt; do
  valid "$RUN/out/${p:t:r}.json" || todo+=$p
done
if (( ${#todo} == 0 )); then
  echo "$RUN: every prompt already has a valid answer; nothing to do."
  exit 0
fi

# xargs runs at most six of these at once; each one answers a single prompt.
VERSION=$("$CODEX_CLI" --version)
export VERSION
print -l $todo | xargs -P 6 -n 1 zsh -c '
  p=$1; name=${p:t:r}
  "$CODEX_CLI" exec --skip-git-repo-check -C "$WORK" -s read-only --ephemeral \
    -m "$CODEX_MODEL" -c model_reasoning_effort="medium" \
    --output-schema "$RUN/schema.json" \
    -o "$RUN/out/$name.json" - < "$p" > "$RUN/logs/$name.log" 2>&1
  if [[ -s "$RUN/out/$name.json" ]] && "$PYTHON" -c "import json, sys; assert isinstance(json.load(open(sys.argv[1]))[\"labels\"], list)" "$RUN/out/$name.json" 2>/dev/null; then
    echo "$CODEX_MODEL, reasoning effort medium, $VERSION" > "$RUN/out/$name.model"
    echo "$name answered"
  else
    [[ -e "$RUN/out/$name.json" ]] && mv "$RUN/out/$name.json" "$RUN/out/$name.bad"
    echo "$name FAILED, see $RUN/logs/$name.log"
  fi' _ || true

left=0
for p in "$RUN"/prompts/slice_*.txt; do valid "$RUN/out/${p:t:r}.json" || (( left += 1 )); done
total=$(ls "$RUN"/prompts/slice_*.txt | wc -l | tr -d ' ')
echo "$RUN: $(( total - left )) of $total prompts answered"
(( left == 0 )) || { echo "$left prompts still without a valid answer; run this script again." >&2; exit 1; }
