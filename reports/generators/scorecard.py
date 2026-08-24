#!/usr/bin/env python3
"""Cross-event generalization scorecard for the framing instrument.
Identical metrics over each event's framing.jsonl — does the schema cover new domains?"""
import json, collections, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.events_coverage import faithfulness as FA

EVENTS=[("Kursk (war)","kursk_2025w11"),
        ("Trump–Zelensky (diplomacy)","trump_zelensky_2025w10"),
        ("Price rises (economic)","prices_2025w11")]
ALL_ROLES=["aggressor","defender","liberator","occupier","victim","perpetrator","hero","villain",
           "provocateur","ally","mediator","protector","threat","beneficiary","traitor","neutral_actor","bystander","other"]
SEM=["conflict","human_interest","economic_consequences","morality","responsibility"]
EPI=["asserted","attributed","hedged","denied","questioned"]

def load(slug):
    p=ROOT/f"data/interim/event_{slug}_framing.jsonl"
    if not p.exists(): return None
    return [json.loads(l) for l in open(p,encoding="utf-8")]

def metrics(R):
    N=len(R)
    roles=collections.Counter(); pol_oor=intens_oor=n_role=0
    for r in R:
        for m in r.get("moral_evaluation") or []:
            roles[m.get("role")]+=1; n_role+=1
            p=m.get("polarity"); i=m.get("intensity")
            if isinstance(p,int) and not(-2<=p<=2): pol_oor+=1
            if isinstance(i,int) and not(0<=i<=2): intens_oor+=1
    epi=collections.Counter(r.get("epistemic_status") for r in R)
    sem=collections.Counter()
    for r in R:
        s=r.get("semetko") or {}
        for f in SEM:
            if s.get(f): sem[f]+=1
    etypes=set()
    n_ent=n_lab=0
    for r in R:
        for e in r.get("entities") or []:
            if e.get("type"): etypes.add(e["type"].strip().lower())
            n_ent+=1
        n_lab+=len(r.get("action_labels") or [])
    val=collections.Counter()
    for r in R:
        for a in r.get("action_labels") or []:
            val[a.get("valence")]+=1
    prov=FA.provenance_summary(R)
    role_cov=sum(1 for r in R if (r.get("moral_evaluation") or []))/N
    causal_null=sum(1 for r in R if not (r.get("causal_attribution") or {}).get("cause_entity"))/N
    treat_null=sum(1 for r in R if not r.get("treatment"))/N
    off=sum(1 for r in R if not r.get("on_event",True))
    return dict(N=N,roles=roles,n_role=n_role,epi=epi,sem=sem,val=val,
        etypes=len(etypes),n_ent=n_ent,n_lab=n_lab,prov=prov,role_cov=role_cov,
        causal_null=causal_null,treat_null=treat_null,off=off,
        pol_oor=pol_oor,intens_oor=intens_oor,
        other_neutral=(roles["other"]+roles["neutral_actor"])/n_role if n_role else 0,
        dead=[r for r in ALL_ROLES if roles[r]==0])

data=[(lbl,slug,metrics(R)) for lbl,slug in EVENTS if (R:=load(slug)) is not None]
W=26
def row(label, vals):
    print(f"  {label:<30}" + "".join(f"{v:>{W}}" for v in vals))

print("="*(30+W*len(data)))
print("FRAMING INSTRUMENT — CROSS-EVENT GENERALIZATION SCORECARD")
print("="*(30+W*len(data)))
row("", [l for l,_,_ in data])
row("", ["─"*16 for _ in data])
row("messages", [f"{m['N']}" for _,_,m in data])
row("off-event flagged", [f"{m['off']}" for _,_,m in data])
print()
row("ROLE coverage (msgs w/ ≥1)", [f"{m['role_cov']*100:.0f}%" for _,_,m in data])
row("role assignments", [f"{m['n_role']}" for _,_,m in data])
row("  % other+neutral_actor", [f"{m['other_neutral']*100:.0f}%" for _,_,m in data])
row("  dead roles (0 uses)", [f"{len(m['dead'])}/18" for _,_,m in data])
print()
print("  TOP 5 ROLES per event:")
for l,_,m in data:
    top=", ".join(f"{r}={c}" for r,c in m['roles'].most_common(5))
    print(f"    {l}: {top}")
print()
print("  EPISTEMIC distribution (%):")
for e in EPI:
    row(f"    {e}", [f"{m['epi'].get(e,0)/m['N']*100:.0f}%" for _,_,m in data])
print()
print("  SEMETKO prevalence (%):")
for f in SEM:
    row(f"    {f}", [f"{m['sem'].get(f,0)/m['N']*100:.0f}%" for _,_,m in data])
print()
row("ACTION-LABEL valence pos/neg/neu", [f"{m['val'].get('positive',0)}/{m['val'].get('negative',0)}/{m['val'].get('neutral',0)}" for _,_,m in data])
row("causal cause_entity null %", [f"{m['causal_null']*100:.0f}%" for _,_,m in data])
row("treatment null %", [f"{m['treat_null']*100:.0f}%" for _,_,m in data])
print()
row("entities / msg", [f"{m['n_ent']/m['N']:.1f}" for _,_,m in data])
row("entity.type cardinality", [f"{m['etypes']}" for _,_,m in data])
row("action_labels / msg", [f"{m['n_lab']/m['N']:.1f}" for _,_,m in data])
print()
row("provenance mean", [f"{m['prov']['mean_score']:.3f}" for _,_,m in data])
row("  % fully grounded", [f"{m['prov']['pct_fully_grounded']*100:.0f}%" for _,_,m in data])
row("intensity out-of-range %", [f"{m['intens_oor']/m['n_role']*100:.0f}%" if m['n_role'] else "—" for _,_,m in data])
row("polarity out-of-range %", [f"{m['pol_oor']/m['n_role']*100:.1f}%" if m['n_role'] else "—" for _,_,m in data])
print("="*(30+W*len(data)))
