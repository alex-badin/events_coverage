#!/bin/zsh
# Send finished month files to Neo and embed them there; repeats until all 63 months are embedded. Budget in the Neo script.
cd ${0:A:h:h:h}
H=$(grep ^NEO_HOST .env | cut -d= -f2); N=data/interim/history/to_neo
while true; do
  if pgrep -f prepare_history.py >/dev/null; then files=($(ls -t $N/*.gz | tail -n +2)); else files=($N/*.gz); fi
  scp -q $files $H:'C:/emb_test/ec/data/interim_history/'
  ssh $H 'cd /d C:\emb_test\ec && C:\emb_test\numpy_env\Scripts\python.exe neo_embed_history.py data\interim_history data\processed\history_fulltext 9 2>&1'
  have=$(ssh $H 'dir /b C:\emb_test\ec\data\processed\history_fulltext\*.f16 | find /c "f16"' | tr -d '\r ')
  echo "$(date -u +%H:%M) $have months embedded"
  [[ $have -ge 63 ]] && break
  sleep 120
done
echo finished
