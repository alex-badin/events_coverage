import collections, numpy as np
import stats_lib as S

SEM=["conflict","responsibility","morality","human_interest","economic_consequences"]
TOP_ENT={"kursk_2025w11":["Russian Armed Forces","Ukrainian Armed Forces"],
         "trump_zelensky_2025w10":["Volodymyr Zelenskyy","Donald Trump"]}

def grp(r): return S.SHORT.get(r["media_group"],r["media_group"])

def dimensions(slug):
    R=S.load(slug)
    gtot=collections.Counter(grp(r) for r in R)
    G=[x for x in S.GORDER if gtot.get(x,0)>=15]
    dims=[]
    def add(name,unit,table,note=""): dims.append(dict(name=name,unit=unit,table=table,note=note,G=G))
    # epistemic (per message)
    t=collections.defaultdict(lambda:collections.Counter())
    for r in R: t[r.get("epistemic_status")][grp(r)]+=1
    add("Epistemic status","message",t)
    # valence (per action_label)
    t=collections.defaultdict(lambda:collections.Counter())
    for r in R:
        for a in r.get("action_labels") or []: t[a.get("valence")][grp(r)]+=1
    add("Action-label valence","loaded term",t)
    # role category (per moral_eval)
    t=collections.defaultdict(lambda:collections.Counter())
    for r in R:
        for m in r.get("moral_evaluation") or []:
            if m.get("role"): t[S.rcat(m["role"])][grp(r)]+=1
    add("Role type (cast)","role assignment",t)
    # semetko per frame (binary)
    for f in SEM:
        t=collections.defaultdict(lambda:collections.Counter())
        for r in R:
            present=bool((r.get("semetko") or {}).get(f))
            t["present" if present else "absent"][grp(r)]+=1
        add(f"Frame: {f}","message",t)
    # prescribes remedy (binary)
    t=collections.defaultdict(lambda:collections.Counter())
    for r in R: t["prescribes" if r.get("treatment") else "none"][grp(r)]+=1
    add("Prescribes a remedy","message",t)
    # cause_entity collapsed
    ce=collections.Counter((r.get("causal_attribution") or {}).get("cause_entity") for r in R if (r.get("causal_attribution") or {}).get("cause_entity"))
    top=[e for e,_ in ce.most_common(5)]
    t=collections.defaultdict(lambda:collections.Counter())
    for r in R:
        c=(r.get("causal_attribution") or {}).get("cause_entity")
        if not c: continue
        t[c if c in top else "(other)"][grp(r)]+=1
    add("Blamed entity (cause)","message w/ cause",t)
    # clusters
    for field in ["problem_definition","causal","treatment"]:
        lab,k,sil=S.cluster_labels(slug,field)
        t=collections.defaultdict(lambda:collections.Counter())
        for r in R:
            cid=lab.get(r.get("message_id"))
            if cid is not None: t[f"C{cid}"][grp(r)]+=1
        add(f"{field} cluster (k={k})","message",t,note=f"silhouette {sil:.2f}")
    # cast of actors: role-type per principal entity
    for e in TOP_ENT.get(slug,[]):
        t=collections.defaultdict(lambda:collections.Counter())
        for r in R:
            for m in r.get("moral_evaluation") or []:
                if m.get("entity")==e and m.get("role"): t[S.rcat(m["role"])][grp(r)]+=1
        add(f"Cast: {e}","role assignment",t)
    return dims

for slug in ["kursk_2025w11","trump_zelensky_2025w10"]:
    dims=dimensions(slug)
    results=[]
    for d in dims:
        res=S.test(d["table"],d["G"])
        if res: results.append((d,res))
    pv=S.holm([res["p"] for _,res in results])
    print("\n"+"#"*92); print(f"# {slug}  — {len(results)} dimensions tested, groups={results[0][0]['G']}"); print("#"*92)
    print(f"{'dimension':<34}{'unit':<16}{'n':>6}{'chi2':>9}{'dof':>5}{'p':>10}{'V':>7}{'holm':>10}  flags")
    order=sorted(range(len(results)),key=lambda i:-results[i][1]["v"])
    for i in order:
        d,res=results[i]; flag=""
        if res["pct_lt5"]>0.2: flag+=f" ⚠{res['pct_lt5']*100:.0f}%exp<5"
        sig="***" if pv[i]<.001 else "**" if pv[i]<.01 else "*" if pv[i]<.05 else "ns"
        print(f"{d['name']:<34}{d['unit']:<16}{res['n']:>6}{res['chi2']:>9.1f}{res['dof']:>5}{res['p']:>10.1e}{res['v']:>7.2f}{pv[i]:>10.1e} {sig}{flag}")
