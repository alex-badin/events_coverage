#!/bin/zsh
# Current Codex limits of one account: a one-word call, then the latest reading across its newest session logs.
cli=${1:-codex-secondary}; home=${2:-$HOME/.codex-secondary}
cd /tmp && $cli exec --ignore-user-config --skip-git-repo-check -s read-only -m gpt-6-luna -c model_reasoning_effort=\"low\" "Reply: ok" </dev/null >/dev/null 2>&1
ls -t $home/sessions/*/*/*/*.jsonl | head -8 | python3 -c "import sys,json
best=None
for f in sys.stdin:
  for l in open(f.strip(),errors='ignore'):
    if '\"rate_limits\"' in l:
      d=json.loads(l); r=d.get('payload',{}).get('rate_limits')
      if r and (not best or d['timestamp']>best[0]): best=(d['timestamp'],r)
if best: print(best[0],'window',best[1]['primary'],'week',best[1]['secondary'])"
