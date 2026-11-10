#!/bin/zsh
# Late months, newest first, embedded on the Mac and pushed to Neo as binary vectors: on Neo's slow link a vector
# costs about 8 KB this way and about 22 KB as base64 JSON. Stops where Neo's own loop (oldest first) has reached.
cd ${0:A:h:h:h}
H=$(grep ^NEO_HOST .env | cut -d= -f2); R='C:\emb_test\ec\data\processed\history_fulltext'; T=data/interim/history/mac_vectors
mkdir -p $T
export OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2- | tr -d '"')
for m in $(ls data/interim/history/to_neo | sed 's/.txt.gz//' | sort -r); do
  if ssh $H "if exist $R\\$m.f16 (echo yes) else if exist $R\\$m.f16.tmp (echo yes) else (echo no)" | grep -q yes; then
    echo "$(date -u +%H:%M) $m is on Neo already; stopping"; break
  fi
  neo_spent=$(ssh $H "type $R\\spend.jsonl" | python3 -c "import sys,json;print(sum(json.loads(l)['usd'] for l in sys.stdin))")
  mac_spent=$(python3 -c "import json,os;print(sum(json.loads(l)['usd'] for l in open('$T/spend.jsonl')) if os.path.exists('$T/spend.jsonl') else 0)")
  cap=$(python3 -c "print(max(0.0, 9 - $neo_spent))")
  .venv/bin/python exploration/2026-11-06_history_vectors/neo_embed_history.py data/interim/history/to_neo $T $cap $m $m || break
  scp -q $T/$m.owners.npy $H:"C:/emb_test/ec/data/processed/history_fulltext/" && scp -q $T/$m.f16 $H:"C:/emb_test/ec/data/processed/history_fulltext/$m.f16.push" && \
    ssh $H "move /y $R\\$m.f16.push $R\\$m.f16" >/dev/null && rm -f $T/$m.f16
  echo "$(date -u +%H:%M) $m on Neo; Neo spent $neo_spent, Mac spent $mac_spent"
done
echo finished
