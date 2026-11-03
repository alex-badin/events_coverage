#!/bin/zsh
# Fable 5.1 as a third reference: the same 150 prompt files Astra got (judges/astra/prompts/, no brief),
# run through Claude Code on the personal Max login (the Team login refuses Fable). One answer per file
# in judges/fable/out/; files already answered are skipped. Usage: fable_judge.sh [stem ...] (default: all).
J=${0:A:h}/../../data/interim/ten_events_readers/judges
cd "${TMPDIR:-/tmp}"   # no project CLAUDE.md, hooks or settings
for p in ${@:+${@/#/$J/astra/prompts/}} ${@:-$J/astra/prompts/*.txt}; do
  p=${p%.txt}.txt; s=${p:t:r}; o=$J/fable/out/$s.json
  [[ -s $o ]] && continue
  CLAUDE_CONFIG_DIR=~/.claude-personal claude -p --model claude-fable-5-1 --output-format json \
    --json-schema "$(cat $J/astra/schema.json)" --tools "" --strict-mcp-config --no-session-persistence \
    --setting-sources "" --system-prompt "Ты размечаешь новостные посты. Следуй инструкции пользователя." \
    < $p > $J/fable/logs/$s.json 2> $J/fable/logs/$s.err \
  && python3 -c "import json,sys; d=json.load(open(sys.argv[1])); r=d.get('structured_output') or json.loads(d['result']); json.dump(r,open(sys.argv[2],'w'),ensure_ascii=False)" $J/fable/logs/$s.json $o \
  || echo "$s failed"
done
