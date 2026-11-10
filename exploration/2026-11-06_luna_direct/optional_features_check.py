#!/usr/bin/env python3
"""Isolated real-data A/B: no production imports, outputs, claims or process changes.
prepare ROOT OUT; run OUT; evaluate OUT. Run makes 12 authorized subscription calls.
"""
import ast
import concurrent.futures
import hashlib
import json
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SLUGS = ['trump_statements_2025w10', 'putin_lukashenko_2025w11', 'drones_moscow_2025w11']
SEED = 20261107

def write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

def digest(b):
    return hashlib.sha256(b).hexdigest()

def metric(ids, truth, scores, cut, weights=None):
    w = weights or dict.fromkeys(ids, 1)
    tp = sum(w[i] for i in ids if truth[i] and scores[i] >= cut)
    fp = sum(w[i] for i in ids if not truth[i] and scores[i] >= cut)
    fn = sum(w[i] for i in ids if truth[i] and scores[i] < cut)
    tn = sum(w[i] for i in ids if not truth[i] and scores[i] < cut)
    pos, neg = [i for i in ids if truth[i]], [i for i in ids if not truth[i]]
    auc = sum(w[i]*w[j]*(1 if scores[i]>scores[j] else .5 if scores[i]==scores[j] else 0)
              for i in pos for j in neg) / (sum(w[i] for i in pos)*sum(w[j] for j in neg)) if pos and neg else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, errors=fp+fn, f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0, auc=auc)

def prepare(root, out):
    assert not out.exists(), 'Use a new output directory; never overwrite an experiment.'
    b = root/'data/interim'
    source = root/'exploration/2026-11-06_luna_direct/luna_scores.py'
    raw = source.read_bytes()
    tail = next(ast.literal_eval(n.value) for n in ast.parse(raw).body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='TAIL' for t in n.targets))
    schema = (b/'luna_direct/score_schema.json').read_bytes()
    inputs = {str(source): digest(raw), str(b/'luna_direct/score_schema.json'): digest(schema)}
    def read(p):
        buf=p.read_bytes(); inputs[str(p)]=digest(buf); return buf.decode()
    events = {}
    prompts = {}
    for slug in SLUGS:
        sol = json.loads(read(b/'jev_selection/holdout_labels'/f'{slug}.json'))
        truth_sol = {int(k): v for k,v in sol['labels'].items()}
        weights = {int(k): v for k,v in sol['weights'].items()}
        votes = {i: [v] for i,v in truth_sol.items()}
        assert len(votes)==750
        for judge in ['astra', 'fable']:
            labels={}
            for p in sorted((b/f'ten_events_readers/judges/{judge}/out').glob(f'{slug}_[0-9][0-9][0-9].json')):
                for x in json.loads(read(p))['labels']:
                    i=int(x['id']); assert i not in labels; assert x['label'] in ['yes','no']; labels[i]=x['label']=='yes'
            assert set(labels)==set(votes)
            for i in votes: votes[i].append(labels[i])
        majority={i: sum(v)>=2 for i,v in votes.items()}
        historical={}
        for p in sorted((b/'luna_direct/variants/c1000_n100').glob(f'{slug}_[0-9][0-9][0-9].json')):
            for x in json.loads(read(p))['scores']:
                i=int(x['id']); assert i not in historical; historical[i]=x['score']
        assert set(historical)==set(votes)
        texts={}; head=None
        for p in sorted((b/'ten_events_readers/reader_labelling/prompts').glob(f'{slug}_[0-9][0-9][0-9].txt')):
            text=read(p); markers=list(re.finditer(r'(?m)^\[id (\d+)\] ',text))
            assert markers
            this_head=text[:markers[0].start()]
            if head is None: head=this_head
            assert head==this_head
            for k,m in enumerate(markers):
                i=int(m.group(1)); body=text[m.end():markers[k+1].start() if k+1<len(markers) else len(text)].rstrip('\n')
                assert i not in texts or texts[i]==body[:1000]
                texts[i]=body[:1000]
        assert set(votes)<=set(texts)
        rng=random.Random(SEED)
        groups={'unanimous_yes':[i for i in sorted(votes) if sum(votes[i])==3],
                'unanimous_no':[i for i in sorted(votes) if sum(votes[i])==0],
                'disagreement':[i for i in sorted(votes) if 0<sum(votes[i])<3]}
        chosen={g:rng.sample(ids,40 if g=='disagreement' else 30) for g,ids in groups.items()}
        ids=sum(chosen.values(),[]); rng.shuffle(ids); assert len(set(ids))==100
        calibration=sorted(set(votes)-set(ids)); assert len(calibration)==650
        # Same >= convention and ascending-score tie break as evaluate.best_cut.
        candidates=sorted({historical[i] for i in calibration})
        def cal_f1(c):
            tp=sum(weights[i] for i in calibration if truth_sol[i] and historical[i]>=c)
            fp=sum(weights[i] for i in calibration if not truth_sol[i] and historical[i]>=c)
            fn=sum(weights[i] for i in calibration if truth_sol[i] and historical[i]<c)
            return 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0
        cut=max(candidates,key=cal_f1)
        prompt=head+'\n\n'.join(f'[id {i}] {texts[i]}' for i in ids)+'\n'+tail
        prompts[slug]=prompt
        events[slug]=dict(ids=ids, strata=chosen, truth={str(i):majority[i] for i in ids},
                          votes={str(i):votes[i] for i in ids}, cut=50, historical_calibration_cut=cut,
                          calibration_ids=calibration, calibration_f1=cal_f1(cut),
                          prompt_sha256=digest(prompt.encode()), prompt_bytes=len(prompt.encode()))
    cli='/opt/homebrew/bin/codex'
    version=subprocess.run([cli,'--version'],capture_output=True,text=True,check=True).stdout.strip()
    protocol=dict(created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), root=str(root), seed=SEED,
                  cli=cli,cli_version=version, model='gpt-6-luna', effort='low', max_concurrency=2,
                  variants={'default':[], 'lean':['--disable','plugins','--disable','apps']},
                  repetitions=2,order=['default_r1','lean_r1','lean_r2','default_r2'],
                  reference='Majority of Sol, Astra, Fable; model labels, not human truth.',
                  evaluation='Unweighted targeted sample, 30 unanimous yes + 30 unanimous no + 40 disagreement per event; not an estimate for the full corpus.',
                  calibration='Primary: score >= 50 for all events, fixed before calls. Secondary: historical scores on remaining 650 posts, weighted F1 against Sol. Production cutoffs are calibrated later and are not tested here.',
                  acceptance={'complete_valid_outputs':True, 'total_errors_lean_lte_default':True,
                              'macro_f1_lean_gte_default':True, 'macro_auc_max_drop':0.005,
                              'per_event_f1_max_drop':'max(0.02, abs(default_r1 F1 - default_r2 F1))'},
                  input_sha256=inputs,events=events)
    out.mkdir(parents=True)
    (out/'schema.json').write_bytes(schema)
    (out/'luna_scores.before.py').write_bytes(raw)
    for slug,prompt in prompts.items(): (out/f'{slug}.txt').write_text(prompt)
    write(out/'protocol.json',protocol)
    print(json.dumps({'prepared':str(out),'protocol_sha256':digest((out/'protocol.json').read_bytes()),
                      'events':{s:{'cut':e['cut'],'positive':sum(e['truth'].values()),'bytes':e['prompt_bytes']} for s,e in events.items()}}),flush=True)

def run_event(out,p,slug):
    prompt=(out/f'{slug}.txt').read_text()
    assert digest(prompt.encode())==p['events'][slug]['prompt_sha256']
    for name in p['order']:
        variant=name.split('_')[0]; result=out/f'{slug}.{name}.json'; meta=out/f'{slug}.{name}.meta.json'
        assert not result.exists() and not meta.exists(), 'No automatic retry or overwrite.'
        started=time.time()
        with tempfile.TemporaryDirectory(prefix='codex-flags-ab-') as work:
            argv=[p['cli'],'exec','--ignore-user-config','--json','--skip-git-repo-check','-C',work,'-s','read-only','--ephemeral',
                  *p['variants'][variant],'-m',p['model'],'-c',f'model_reasoning_effort="{p["effort"]}"',
                  '--output-schema',str(out/'schema.json'),'-o',str(result),'-']
            proc=subprocess.run(argv,input=prompt,capture_output=True,text=True,timeout=600)
        usage=[]; types={}; errors=[]
        for line in proc.stdout.splitlines():
            try: event=json.loads(line)
            except ValueError: continue
            typ=event.get('type','unknown');types[typ]=types.get(typ,0)+1
            if event.get('usage'):usage.append(event['usage'])
            if typ in ['error','turn.failed']: errors.append(event)
        record=dict(name=name,slug=slug,returncode=proc.returncode,elapsed_seconds=round(time.time()-started,3),
                    started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(started)),
                    prompt_sha256=digest(prompt.encode()), usage=usage,event_types=types,errors=errors,
                    stderr_bytes=len(proc.stderr.encode()),output_exists=result.exists())
        write(meta,record)
        print(json.dumps(record),flush=True)
        if proc.returncode!=0 or not result.exists(): raise RuntimeError(f'Call failed: {slug}.{name}; no automatic retries.')

def run(out):
    p=json.loads((out/'protocol.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run_event,out,p,slug) for slug in p['events']]
        for f in futures:f.result()

def evaluate(out):
    p=json.loads((out/'protocol.json').read_text()); rows={}; comparisons={}; all_scores={}
    for slug,e in p['events'].items():
        ids=e['ids']; truth={int(i):v for i,v in e['truth'].items()}; rows[slug]={}; all_scores[slug]={}
        for name in p['order']:
            data=json.loads((out/f'{slug}.{name}.json').read_text())
            assert set(data)=={'scores'}
            scores={}
            for x in data['scores']:
                assert set(x)=={'id','score'} and isinstance(x['id'],str) and x['id'].isdigit()
                i=int(x['id']); assert i not in scores and type(x['score']) is int and 0<=x['score']<=100
                scores[i]=x['score']
            assert set(scores)==set(ids)
            rows[slug][name]=metric(ids,truth,scores,e['cut']); rows[slug][name]['historical_cut_metric']=metric(ids,truth,scores,e['historical_calibration_cut']); all_scores[slug][name]=scores
        comparisons[slug]={}
        for a,b in [('default_r1','lean_r1'),('default_r2','lean_r2'),('default_r1','default_r2'),('lean_r1','lean_r2')]:
            sa,sb=all_scores[slug][a],all_scores[slug][b]
            good_bad=[i for i in ids if (sa[i]>=e['cut'])==truth[i] and (sb[i]>=e['cut'])!=truth[i]]
            bad_good=[i for i in ids if (sa[i]>=e['cut'])!=truth[i] and (sb[i]>=e['cut'])==truth[i]]
            comparisons[slug][f'{a}_to_{b}']=dict(good_to_bad=good_bad,bad_to_good=bad_good,mean_absolute_score_change=sum(abs(sa[i]-sb[i]) for i in ids)/len(ids))
    averages={}
    for variant in ['default','lean']:
        values=[rows[s][f'{variant}_r{r}'] for s in rows for r in [1,2]]
        averages[variant]={'classifications':600,'errors':sum(v['errors'] for v in values),
                           'macro_f1':sum(v['f1'] for v in values)/len(values),'macro_auc':sum(v['auc'] for v in values)/len(values)}
    gates={
        'complete_valid_outputs':True,
        'total_errors_lean_lte_default':averages['lean']['errors']<=averages['default']['errors'],
        'macro_f1_lean_gte_default':averages['lean']['macro_f1']+1e-12>=averages['default']['macro_f1'],
        'macro_auc_drop_within_limit':averages['lean']['macro_auc']+0.005+1e-12>=averages['default']['macro_auc']}
    for slug,row in rows.items():
        a=(row['default_r1']['f1']+row['default_r2']['f1'])/2;b=(row['lean_r1']['f1']+row['lean_r2']['f1'])/2
        spread=abs(row['default_r1']['f1']-row['default_r2']['f1'])
        gates[f'{slug}_f1_drop_within_limit']=a-b<=max(.02,spread)+1e-12
    result=dict(protocol_sha256=digest((out/'protocol.json').read_bytes()),events=rows,comparisons=comparisons,
                aggregate=averages,gates=gates,accepted=all(gates.values()))
    write(out/'evaluation.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    if sys.argv[1]=='prepare': prepare(Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
    elif sys.argv[1]=='run':run(Path(sys.argv[2]).resolve())
    elif sys.argv[1]=='evaluate':evaluate(Path(sys.argv[2]).resolve())
    else: raise SystemExit('prepare ROOT OUT | run OUT | evaluate OUT')
