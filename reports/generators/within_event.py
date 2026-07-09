#!/usr/bin/env python3
"""Do the framing parameters separate MEDIA GROUPS within a single event?
For each event: per-group rates, the spread across groups, and a plain verdict."""
import json, collections, statistics
from pathlib import Path
ROOT=Path("/Users/alexbadin/GitHub/_projects/events_coverage")
EVENTS=[("KURSK — war","kursk_2025w11"),
        ("TRUMP–ZELENSKY — diplomacy","trump_zelensky_2025w10"),
        ("PRICE RISES — economic","prices_2025w11")]
MINN=15   # below this a group is too small to read
def clip(p):
    return max(-2,min(2,p)) if isinstance(p,(int,float)) else None

def load(slug):
    return [json.loads(l) for l in open(ROOT/f"data/interim/event_{slug}_framing.jsonl",encoding="utf-8")]

def verdict_pct(spread):
    return "STRONG" if spread>=25 else "some" if spread>=10 else "little"
def verdict_pol(spread):
    return "STRONG" if spread>=0.7 else "some" if spread>=0.3 else "little"

for label,slug in EVENTS:
    R=load(slug)
    R=[r for r in R if r.get("on_event",True)]
    G=collections.Counter(r["media_group"] for r in R)
    groups=[g for g,_ in G.most_common()]
    big=[g for g in groups if G[g]>=MINN]
    print("\n"+"="*78); print(f"{label}   (n={len(R)})"); print("="*78)
    print("groups:", ", ".join(f"{g.split(' and ')[0].split(' (')[0][:18]}={G[g]}" for g in groups))
    print(f"(reading only groups with n>={MINN}: {len(big)} of {len(groups)})")
    if len(big)<2:
        print(">> Too few sizeable groups to compare within this event. Skipping group analysis.")
        continue

    short={g:g.split(' and ')[0].split(' (')[0][:16] for g in big}

    # ---- 1. epistemic 'own voice' (% asserted) ----
    asr={g: round(100*sum(1 for r in R if r["media_group"]==g and r.get("epistemic_status")=="asserted")/G[g]) for g in big}
    sp=max(asr.values())-min(asr.values())
    print(f"\n1) Speaks in OWN VOICE (% asserted, not sourced)   [{verdict_pct(sp)} separator, spread {sp} pts]")
    for g in sorted(big,key=lambda x:-asr[x]): print(f"     {asr[g]:3d}%  {short[g]}")

    # ---- 2. valence tilt (% positive action labels) ----
    pos={}
    for g in big:
        labs=[a.get("valence") for r in R if r["media_group"]==g for a in (r.get("action_labels") or [])]
        pos[g]=round(100*sum(1 for v in labs if v=="positive")/len(labs)) if labs else 0
    sp=max(pos.values())-min(pos.values())
    print(f"\n2) Word-choice tilt (% of loaded terms that are POSITIVE)  [{verdict_pct(sp)}, spread {sp} pts]")
    for g in sorted(big,key=lambda x:-pos[x]): print(f"     {pos[g]:3d}%  {short[g]}")

    # ---- 3. stance toward the central shared actors (mean polarity, clipped) ----
    ment=collections.Counter()
    for r in R:
        for m in r.get("moral_evaluation") or []:
            if m.get("entity"): ment[m["entity"]]+=1
    central=[e for e,_ in ment.most_common(4)]
    print(f"\n3) STANCE toward the main actors (mean −2..+2, n in parens; clipped)")
    print(f"     {'actor':<26}" + "".join(f"{short[g]:>14}" for g in big))
    for e in central:
        cells=[]; vals=[]
        for g in big:
            ps=[clip(m.get('polarity')) for r in R if r['media_group']==g for m in (r.get('moral_evaluation') or []) if m.get('entity')==e and clip(m.get('polarity')) is not None]
            if len(ps)>=3:
                mv=statistics.mean(ps); vals.append(mv); cells.append(f"{mv:+.1f}({len(ps)})")
            else:
                cells.append(f"  ·")
        if len(vals)>=2:
            sp=max(vals)-min(vals); tag=verdict_pol(sp)
        else: tag="—"
        print(f"     {e[:26]:<26}"+"".join(f"{c:>14}" for c in cells)+f"   [{tag}]")

    # ---- 4. soft frames: human_interest & morality ----
    for frame in ["human_interest","morality"]:
        fr={g: round(100*sum(1 for r in R if r['media_group']==g and (r.get('semetko') or {}).get(frame))/G[g]) for g in big}
        sp=max(fr.values())-min(fr.values())
        print(f"\n4) Uses {frame.replace('_',' ').upper()} angle (%)   [{verdict_pct(sp)}, spread {sp} pts]")
        print("     "+"   ".join(f"{short[g]} {fr[g]}%" for g in sorted(big,key=lambda x:-fr[x])))
