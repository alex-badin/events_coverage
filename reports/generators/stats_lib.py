"""Contingency + chi-square/Cramer's V engine for framing dimensions vs media group."""
import json, collections, numpy as np
from scipy.stats import chi2_contingency
import cluster_lib as C

SHORT={"Federal TV and state broadcasters":"fedTV","Independent and exile media":"indep","Mainstream business and general media":"biz","War and military channels":"war","State agencies":"state","Pro-government online media":"progov"}
GORDER=["state","progov","fedTV","biz","war","indep"]
APPROVE={"liberator","hero","defender","protector","ally","beneficiary","mediator"}
CONDEMN={"aggressor","occupier","villain","threat","perpetrator","provocateur","traitor"}
def rcat(r): return "favourable" if r in APPROVE else "unfavourable" if r in CONDEMN else "victim" if r=="victim" else "neutral"

def load(slug):
    return [r for r in (json.loads(l) for l in open(f"/Users/alexbadin/GitHub/_projects/events_coverage/data/interim/event_{slug}_framing.jsonl",encoding="utf-8")) if r.get("on_event",True)]

def cluster_labels(slug, field):
    """message_id -> cluster id, plus k."""
    X,texts,groups,sources,causes,ids=C.load(slug,field)
    Xn=C.l2(X); n=len(texts); hi=min(12,max(4,n//22))
    k,sil,labels=C.pick_k_kmeans(Xn,3,hi)
    return {ids[i]:int(labels[i]) for i in range(len(ids))}, k, sil

def cramers_v(chi2, n, r, c):
    return float(np.sqrt(chi2/(n*(min(r,c)-1)))) if n and min(r,c)>1 else 0.0

def test(table, groups):
    """table: {category: {group: count}} -> stats dict. groups: ordered list to use as columns."""
    cats=[cat for cat in table if sum(table[cat].get(g,0) for g in groups)>0]
    M=np.array([[table[cat].get(g,0) for g in groups] for cat in cats],dtype=float)
    # drop all-zero columns
    keep=[j for j in range(M.shape[1]) if M[:,j].sum()>0]
    M=M[:,keep]; cols=[groups[j] for j in keep]
    if M.shape[0]<2 or M.shape[1]<2:
        return None
    chi2,p,dof,exp=chi2_contingency(M)
    n=M.sum()
    return dict(cats=cats, cols=cols, M=M, chi2=chi2, p=p, dof=dof,
                v=cramers_v(chi2,n,M.shape[0],M.shape[1]), n=int(n),
                min_exp=float(exp.min()), pct_lt5=float((exp<5).mean()))

SEM=["conflict","responsibility","morality","human_interest","economic_consequences"]
TOP_ENT={"kursk_2025w11":["Russian Armed Forces","Ukrainian Armed Forces"],
         "trump_zelensky_2025w10":["Volodymyr Zelenskyy","Donald Trump"]}
def _grp(r): return SHORT.get(r["media_group"],r["media_group"])

def dimensions(slug):
    """Return list of {name,unit,table,note,G} — every aggregatable framing dimension vs media group."""
    R=load(slug)
    gtot=collections.Counter(_grp(r) for r in R)
    G=[x for x in GORDER if gtot.get(x,0)>=15]
    dims=[]
    def add(name,unit,table,note=""): dims.append(dict(name=name,unit=unit,table=table,note=note,G=G))
    def newt(): return collections.defaultdict(lambda:collections.Counter())
    t=newt()
    for r in R: t[r.get("epistemic_status")][_grp(r)]+=1
    add("Epistemic status","message",t)
    t=newt()
    for r in R:
        for a in r.get("action_labels") or []: t[a.get("valence")][_grp(r)]+=1
    add("Action-label valence","loaded term",t)
    t=newt()
    for r in R:
        for m in r.get("moral_evaluation") or []:
            if m.get("role"): t[rcat(m["role"])][_grp(r)]+=1
    add("Role type (overall cast)","role assignment",t)
    for f in SEM:
        t=newt()
        for r in R: t["uses" if (r.get("semetko") or {}).get(f) else "—"][_grp(r)]+=1
        add(f"Frame · {f}","message",t)
    t=newt()
    for r in R: t["prescribes" if r.get("treatment") else "none"][_grp(r)]+=1
    add("Prescribes a remedy","message",t)
    ce=collections.Counter((r.get("causal_attribution") or {}).get("cause_entity") for r in R if (r.get("causal_attribution") or {}).get("cause_entity"))
    top=[e for e,_ in ce.most_common(5)]
    t=newt()
    for r in R:
        c=(r.get("causal_attribution") or {}).get("cause_entity")
        if c: t[c if c in top else "(other)"][_grp(r)]+=1
    add("Blamed entity (cause)","msg w/ cause",t)
    clusterk={}
    for field in ["problem_definition","causal","treatment"]:
        lab,k,sil=cluster_labels(slug,field); clusterk[field]=k
        t=newt()
        for r in R:
            cid=lab.get(r.get("message_id"))
            if cid is not None: t[f"C{cid}"][_grp(r)]+=1
        add(f"{field} cluster","message",t,note=f"k={k}, silhouette {sil:.2f}")
    for e in TOP_ENT.get(slug,[]):
        t=newt()
        for r in R:
            for m in r.get("moral_evaluation") or []:
                if m.get("entity")==e and m.get("role"): t[rcat(m["role"])][_grp(r)]+=1
        add(f"Cast of: {e}","role assignment",t)
    return dims

def holm(pvals):
    """Holm-Bonferroni adjusted p-values, preserving input order."""
    idx=sorted(range(len(pvals)),key=lambda i:pvals[i]); m=len(pvals); adj=[0]*m; prev=0
    for rank,i in enumerate(idx):
        a=min(1.0,(m-rank)*pvals[i]); prev=max(prev,a); adj[i]=prev
    return adj
