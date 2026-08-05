#!/bin/bash
# Ask the user before running anything in this project that spends money.
#
# Wired up as a PreToolUse hook on Bash in .claude/settings.json. Reads the hook payload on
# stdin, decides whether the command would reach a paid service, and if so returns
# permissionDecision "ask" so Claude Code prompts instead of just running it.
#
# WHY THIS EXISTS: on 2026-08-03 an agent read a written rule saying "state the cost and wait
# for agreement", computed the cost, reasoned its way past the rule, and spent about $20.82
# without asking. Prose in an instruction file is advisory. This is not.
#
# WHY IT MATCHES ON CONTENT, NOT ON A LIST OF FILENAMES: a hardcoded list goes stale the
# moment someone adds a script, and it goes stale silently — the same failure the hook is
# meant to prevent. Instead it greps the Python file being run for the things that actually
# cost money. Measured on 2026-08-03 against every .py file in scripts/, src/ and dashboard/:
# the pattern below matches exactly the five spending scripts (build_event_dataset,
# backfill_embeddings_openrouter, bakeoff_embeddings, extract_framing, induce_narratives)
# plus the two library modules they call, and matches none of the free ones — notably not
# load_warehouse.py, which imports the same module but never reaches a paid call.
#
# Test it by hand:
#   echo '{"tool_input":{"command":".venv/bin/python scripts/build_event_dataset.py"}}' \
#     | .claude/hooks/ask-before-paid-run.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Things that cost money: the shared helpers in src/events_coverage/, the vendor SDKs used
# directly, and the API key names. Any new script that spends will touch one of these.
PAID='get_cohere_client|embed_texts|client\.rerank|cohere_rerank|import cohere|OpenAI\(|openai|openrouter|OPENROUTER|COHERE_API_KEY|OPENAI_API_KEY'

payload="$(cat)"
command_text="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[[ -z "$command_text" ]] && exit 0

# Only look at commands that actually run Python. Without this, reading or checking one of
# these files (git diff, cat, ruff) would prompt for no reason. Match the interpreter itself,
# NOT the whole .venv/bin/ directory: `.venv/bin/ruff check build_event_dataset.py` reads the
# file and spends nothing, and an earlier version of this guard prompted on it.
# The test is "the program being run is python", so match a whole executable token ending in
# python — .venv/bin/python, python3, /abs/path/to/python — or `uv run`.
if ! printf '%s' "$command_text" | grep -Eq '(^|[[:space:]]|=)[^[:space:]]*python[0-9.]*([[:space:]]|$)|uv run'; then
  exit 0
fi

reason=""

# Inline code: python -c "from events_coverage.matching import rerank ..." spends money
# without naming any file, so check the command text itself first.
if printf '%s' "$command_text" | grep -Eq "$PAID"; then
  reason="the command itself references a paid call"
fi

# Otherwise check each .py file the command mentions.
if [[ -z "$reason" ]]; then
  while read -r script; do
    [[ -z "$script" ]] && continue
    for candidate in "$script" "$ROOT/$script"; do
      if [[ -f "$candidate" ]] && grep -Eqi "$PAID" "$candidate"; then
        hit="$(grep -Eoi "$PAID" "$candidate" | sort -u | head -3 | paste -sd', ' -)"
        reason="$script reaches a paid service (matched: $hit)"
        break 2
      fi
    done
  done < <(printf '%s' "$command_text" | grep -oE '[][:alnum:]_./-]*\.py' | sort -u)
fi

[[ -z "$reason" ]] && exit 0

jq -cn --arg reason "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "ask",
    permissionDecisionReason: ("This run spends money — " + $reason + ". State the expected number of calls and the cost from the vendor'"'"'s current published price before proceeding.")
  }
}'
