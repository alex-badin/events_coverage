#!/usr/bin/env python3
"""Generate an HTML artifact: every framing field's value distribution, by media group, per event."""
import json, collections, statistics, html
from pathlib import Path
ROOT=Path("/Users/alexbadin/GitHub/_projects/events_coverage")
OUT=Path("/Users/alexbadin/GitHub/_projects/events_coverage/reports/field_distributions.html")

EVENTS=[("Kursk / Sudzha","war","kursk_2025w11"),
        ("Trump–Zelensky in Washington","diplomacy · clash","trump_zelensky_2025w10"),
        ("Putin–Trump phone call","diplomacy · thaw","putin_trump_call_2025w08"),
        ("US–Russia contacts","diplomacy · thaw","us_russia_contacts_2025w09"),
        ("Rising prices & tariffs","economic","prices_2025w11"),
        ("DC air crash","disaster","dc_aircrash_2025w05")]
ROLE_ORDER=["liberator","hero","defender","protector","ally","beneficiary","mediator","victim",
            "neutral_actor","other","aggressor","occupier","villain","threat","perpetrator","provocateur","traitor","bystander"]
APPROVING={"liberator","hero","defender","protector","ally","beneficiary","mediator"}
CONDEMNING={"aggressor","occupier","villain","threat","perpetrator","provocateur","traitor"}
EPI=["asserted","attributed","hedged","denied","questioned"]
EPI_LBL={"asserted":"own voice (asserted)","attributed":"sourced (attributed)","hedged":"hedged","denied":"denied","questioned":"questioned"}
SEM=["conflict","responsibility","morality","human_interest","economic_consequences"]
SEM_LBL={"conflict":"conflict","responsibility":"responsibility","morality":"morality","human_interest":"human interest","economic_consequences":"economic consequences"}
SHORT={"Pro-government online media":"Pro-gov online","Federal TV and state broadcasters":"Federal TV",
       "Mainstream business and general media":"Business/general","State agencies":"State agencies",
       "Independent and exile media":"Independent/exile","War and military channels":"War channels"}
MINN=15
def clip(p): return max(-2,min(2,p)) if isinstance(p,(int,float)) else None
def load(slug):
    R=[json.loads(l) for l in open(ROOT/f"data/interim/event_{slug}_framing.jsonl",encoding="utf-8")]
    return [r for r in R if r.get("on_event",True)]

# ---------- cell shaders ----------
def pct_cell(p, thin=False):
    if p is None: return '<td class="na">·</td>'
    a=min(0.82, p/100*0.92)
    tc="#fff" if p>=55 else "var(--ink)"
    th=' th' if thin else ''
    return f'<td class="num{th}" style="background:rgba(46,58,102,{a:.3f});color:{tc}">{p:.0f}<span class="pctsym">%</span></td>'
def stance_cell(v,n,thin=False):
    if v is None: return '<td class="na">·</td>'
    if v>=0: a=min(0.8,v/2*0.85); bg=f"rgba(44,122,104,{a:.3f})"
    else: a=min(0.8,-v/2*0.85); bg=f"rgba(177,78,44,{a:.3f})"
    tc="#fff" if abs(v)>=1.15 else "var(--ink)"
    th=' th' if thin else ''
    return f'<td class="num{th}" style="background:{bg};color:{tc}">{v:+.1f}<span class="nsub">{n}</span></td>'
def plain_cell(s): return f'<td class="txt">{html.escape(str(s))}</td>'

def table(title, sub, head_groups, rows):
    h='<div class="tblwrap"><table>'
    h+='<thead><tr><th class="rowhdr">'+html.escape(title)+'</th>'
    for g,n in head_groups:
        thin=' thin' if n<MINN else ''
        h+=f'<th class="{thin}">{html.escape(SHORT.get(g,g))}<span class="gn">n={n}</span></th>'
    h+='</tr></thead><tbody>'
    for label, cells in rows:
        h+='<tr><td class="rl">'+label+'</td>'+''.join(cells)+'</tr>'
    h+='</tbody></table></div>'
    if sub: h=f'<p class="tcap">{sub}</p>'+h
    return h

SECTIONS=[]
NAV=[]
for ev_label, ev_kind, slug in EVENTS:
    R=load(slug)
    Gc=collections.Counter(r["media_group"] for r in R)
    groups=[g for g,_ in Gc.most_common()]
    head=[(g,Gc[g]) for g in groups]
    anchor=slug
    NAV.append((ev_label,ev_kind,anchor,len(R),len([g for g in groups if Gc[g]>=MINN])))
    body=[]

    # A. epistemic
    rows=[]
    for e in EPI:
        cells=[]
        for g in groups:
            sub=[r for r in R if r["media_group"]==g]
            p=100*sum(1 for r in sub if r.get("epistemic_status")==e)/len(sub) if sub else None
            cells.append(pct_cell(p, Gc[g]<MINN))
        rows.append((EPI_LBL[e],cells))
    body.append(("How the claim is presented","Share of each group's messages. One value per message.",table("epistemic stance",None,head,rows)))

    # B. valence
    rows=[]
    for v,lbl in [("positive","positive words"),("negative","negative words"),("neutral","neutral words")]:
        cells=[]
        for g in groups:
            labs=[a.get("valence") for r in R if r["media_group"]==g for a in (r.get("action_labels") or [])]
            p=100*sum(1 for x in labs if x==v)/len(labs) if labs else None
            cells.append(pct_cell(p, Gc[g]<MINN))
        rows.append((lbl,cells))
    body.append(("Word-choice loading","Share of each group's loaded action terms.",table("action-label valence",None,head,rows)))

    # C. semetko
    rows=[]
    for f in SEM:
        cells=[]
        for g in groups:
            sub=[r for r in R if r["media_group"]==g]
            p=100*sum(1 for r in sub if (r.get("semetko") or {}).get(f))/len(sub) if sub else None
            cells.append(pct_cell(p, Gc[g]<MINN))
        rows.append((SEM_LBL[f],cells))
    body.append(("News frame used","Share of each group's messages (a message can use several).",table("semetko frames",None,head,rows)))

    # D. roles
    grp_roletot={g:sum(1 for r in R if r["media_group"]==g for m in (r.get("moral_evaluation") or [])) for g in groups}
    present=[]
    for role in ROLE_ORDER:
        tot=sum(1 for r in R for m in (r.get("moral_evaluation") or []) if m.get("role")==role)
        if tot>0: present.append(role)
    rows=[]
    for role in present:
        cells=[]
        for g in groups:
            c=sum(1 for r in R if r["media_group"]==g for m in (r.get("moral_evaluation") or []) if m.get("role")==role)
            p=100*c/grp_roletot[g] if grp_roletot[g] else None
            cells.append(pct_cell(p, Gc[g]<MINN))
        cls="approve" if role in APPROVING else "condemn" if role in CONDEMNING else "amb" if role=="victim" else "neut"
        rows.append((f'<span class="rdot {cls}"></span>{role}',cells))
    dead=[r for r in ROLE_ORDER if r not in present]
    sub="Share of each group's role assignments. "+(f"Never used in this event: {', '.join(dead)}." if dead else "All 18 roles appear.")
    body.append(("Which role each actor is cast in",sub,table("entity roles",None,head,rows)))

    # E. stance toward main actors
    ment=collections.Counter()
    for r in R:
        for m in r.get("moral_evaluation") or []:
            if m.get("entity"): ment[m["entity"]]+=1
    top=[e for e,_ in ment.most_common(6)]
    rows=[]
    for e in top:
        cells=[]
        for g in groups:
            ps=[clip(m.get("polarity")) for r in R if r["media_group"]==g for m in (r.get("moral_evaluation") or []) if m.get("entity")==e and clip(m.get("polarity")) is not None]
            if len(ps)>=3: cells.append(stance_cell(statistics.mean(ps),len(ps),Gc[g]<MINN))
            else: cells.append('<td class="na">·</td>')
        rows.append((html.escape(e),cells))
    body.append(("Stance toward the main actors","Average warmth −2 (hostile) → +2 (warm); small number = mentions. Blank = fewer than 3.",table("stance",None,head,rows)))

    # F. summary scalars
    rows=[]
    def scalar(label, fn, fmt="{:.1f}"):
        cells=[]
        for g in groups:
            sub=[r for r in R if r["media_group"]==g]
            val=fn(sub)
            cells.append(f'<td class="num plain{" th" if Gc[g]<MINN else ""}">{val}</td>' if val is not None else '<td class="na">·</td>')
        rows.append((label,cells))
    def mean_intensity(sub):
        xs=[m.get("intensity") for r in sub for m in (r.get("moral_evaluation") or []) if isinstance(m.get("intensity"),int)]
        return f"{statistics.mean(xs):.1f}" if xs else None
    def treat(sub): return f"{100*sum(1 for r in sub if r.get('treatment'))/len(sub):.0f}%" if sub else None
    def cause(sub): return f"{100*sum(1 for r in sub if (r.get('causal_attribution') or {}).get('cause_entity'))/len(sub):.0f}%" if sub else None
    def ent_per(sub): return f"{statistics.mean([len(r.get('entities') or []) for r in sub]):.1f}" if sub else None
    def lab_per(sub): return f"{statistics.mean([len(r.get('action_labels') or []) for r in sub]):.1f}" if sub else None
    def topcause(sub):
        c=collections.Counter((r.get('causal_attribution') or {}).get('cause_entity') for r in sub if (r.get('causal_attribution') or {}).get('cause_entity'))
        return c.most_common(1)[0][0][:22] if c else "—"
    scalar("avg stance intensity (0–2)",mean_intensity)
    scalar("prescribes a remedy",treat)
    scalar("names a cause",cause)
    scalar("most-named cause",topcause)
    scalar("entities / message",ent_per)
    scalar("loaded terms / message",lab_per)
    body.append(("Summary measures","Per group.",table("summary",None,head,rows)))

    blocks="".join(f'<div class="block"><h3>{html.escape(t)}</h3><p class="bsub">{html.escape(s)}</p>{tb}</div>' for t,s,tb in body)
    SECTIONS.append(f'<section id="{anchor}"><div class="evhead"><span class="evkind">{ev_kind}</span><h2>{html.escape(ev_label)}</h2><span class="evn">{len(R)} messages · {len(groups)} groups</span></div>{blocks}</section>')

navhtml="".join(f'<a href="#{a}"><span class="k">{k}</span><span>{html.escape(l)}</span><span class="nn">{n} msgs · {b} groups read</span></a>' for l,k,a,n,b in NAV)

HTML=f'''<title>Framing field distributions by media group</title>
<meta name="description" content="Every framing field's value distribution across media groups, for six 2025 events spanning war, diplomacy, economic and disaster.">
<style>
:root{{--ground:#E7EAEE;--card:#FCFDFE;--rule:#D3D8DF;--rule2:#E6E9ED;--ink:#161A21;--ink2:#4C5563;--ink3:#828B97;
--accent:#2E3A66;--accent2:#4A5891;--pos:#2C7A68;--neg:#B14E2C;--amb:#9C6B14;--neu:#7E8693;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;}}
*{{box-sizing:border-box}}body{{margin:0}}
.page{{background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.55;padding:0 clamp(14px,3.5vw,44px) 90px}}
.tnum{{font-variant-numeric:tabular-nums}}
header.mast{{max-width:1240px;margin:0 auto;padding:clamp(34px,6vw,64px) 0 22px}}
.eyebrow{{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent2);font-weight:600}}
.mast h1{{font-family:var(--mono);font-weight:680;letter-spacing:-.02em;font-size:clamp(1.7rem,4vw,2.6rem);margin:.5rem 0 0;text-wrap:balance;max-width:20ch}}
.mast p{{color:var(--ink2);max-width:64ch;margin:.9rem 0 0;font-size:1.02rem}}
.legend{{display:flex;flex-wrap:wrap;gap:.5rem 1.4rem;margin:1.4rem 0 0;font-family:var(--mono);font-size:.76rem;color:var(--ink2)}}
.legend .li{{display:flex;align-items:center;gap:.45rem}}
.legend .sw{{width:1.5rem;height:.7rem;border-radius:2px;border:1px solid var(--rule)}}
nav.evnav{{max-width:1240px;margin:1.6rem auto 0;display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
nav.evnav a{{text-decoration:none;background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.7rem .85rem;display:flex;flex-direction:column;gap:.15rem;border-left:3px solid var(--accent)}}
nav.evnav a:hover{{background:#fff;box-shadow:0 1px 0 var(--rule)}}
nav.evnav .k{{font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:var(--accent2)}}
nav.evnav a>span:nth-child(2){{font-weight:600;font-size:.95rem;color:var(--ink)}}
nav.evnav .nn{{font-family:var(--mono);font-size:.72rem;color:var(--ink3)}}
.wrap{{max-width:1240px;margin:0 auto}}
section{{margin-top:clamp(38px,5vw,58px);scroll-margin-top:14px}}
.evhead{{display:flex;align-items:baseline;gap:.8rem;border-bottom:1.5px solid var(--ink);padding-bottom:.5rem;position:sticky;top:0;background:var(--ground);z-index:5}}
.evkind{{font-family:var(--mono);font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;color:#fff;background:var(--accent);padding:.2rem .5rem;border-radius:2px}}
.evhead h2{{font-size:1.25rem;margin:0;font-weight:650}}
.evhead .evn{{margin-left:auto;font-family:var(--mono);font-size:.76rem;color:var(--ink3)}}
.block{{margin-top:1.7rem}}
.block h3{{font-family:var(--mono);font-size:.95rem;letter-spacing:.02em;margin:0;font-weight:600}}
.bsub{{color:var(--ink3);font-size:.83rem;margin:.2rem 0 .7rem}}
.tblwrap{{overflow-x:auto;border:1px solid var(--rule);border-radius:6px;background:var(--card)}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}}
thead th{{position:sticky;top:0;background:#EFF1F4;text-align:right;padding:.55rem .7rem;font-weight:600;font-size:.78rem;color:var(--ink2);border-bottom:1px solid var(--rule);vertical-align:bottom;white-space:nowrap}}
thead th.rowhdr{{text-align:left;font-family:var(--mono);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3)}}
thead th.thin{{color:var(--ink3);font-style:italic}}
.gn{{display:block;font-family:var(--mono);font-weight:400;font-size:.68rem;color:var(--ink3)}}
td.rl{{text-align:left;padding:.4rem .7rem;border-bottom:1px solid var(--rule2);white-space:nowrap;color:var(--ink);font-size:.85rem}}
td.num{{text-align:right;padding:.4rem .7rem;border-bottom:1px solid var(--rule2);border-left:1px solid var(--rule2);font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:.82rem}}
td.num.plain{{background:none}}
td.num.th{{opacity:.5}}
td.txt{{text-align:right;padding:.4rem .7rem;border-bottom:1px solid var(--rule2);border-left:1px solid var(--rule2);font-size:.78rem;color:var(--ink2)}}
td.na{{text-align:right;padding:.4rem .7rem;border-bottom:1px solid var(--rule2);border-left:1px solid var(--rule2);color:var(--ink3)}}
.pctsym{{font-size:.7em;opacity:.6;margin-left:1px}}
.nsub{{font-size:.66em;opacity:.55;margin-left:.3rem;vertical-align:super}}
.rdot{{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;margin-right:.45rem;vertical-align:middle}}
.rdot.approve{{background:var(--pos)}}.rdot.condemn{{background:var(--neg)}}.rdot.amb{{background:var(--amb)}}.rdot.neut{{background:var(--neu)}}
footer{{max-width:1240px;margin:60px auto 0;padding-top:18px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:.75rem;color:var(--ink3);display:flex;flex-wrap:wrap;gap:.4rem 1.4rem}}
@media(max-width:720px){{nav.evnav{{grid-template-columns:1fr}}}}
</style>
<div class="page">
<header class="mast">
<div class="eyebrow">events_coverage · framing fields × media groups</div>
<h1>Field distributions by media group</h1>
<p>Every framing field's value distribution, broken out by media group, for six 2025 events spanning war, diplomacy (a clash and two thaws), economics and a foreign disaster. Read down a column to see one outlet-type's profile; read across a row to see which outlets diverge. Groups with fewer than {MINN} messages are dimmed — too thin to trust. Two events are coverage-limited: <b>prices</b> (only two sizeable groups) and the <b>DC air crash</b> (a foreign tragedy almost everyone simply sourced and reported — uniform framing, little to separate).</p>
<div class="legend">
<span class="li"><span class="sw" style="background:rgba(46,58,102,.12)"></span><span class="sw" style="background:rgba(46,58,102,.45)"></span><span class="sw" style="background:rgba(46,58,102,.8)"></span>&nbsp;low → high share</span>
<span class="li"><span class="sw" style="background:rgba(177,78,44,.6)"></span>hostile stance</span>
<span class="li"><span class="sw" style="background:rgba(44,122,104,.6)"></span>warm stance</span>
<span class="li"><span class="rdot approve"></span>approving role <span class="rdot condemn" style="margin-left:.6rem"></span>condemning <span class="rdot amb" style="margin-left:.6rem"></span>victim <span class="rdot neut" style="margin-left:.6rem"></span>neutral</span>
</div>
</header>
<nav class="evnav">{navhtml}</nav>
<div class="wrap">{''.join(SECTIONS)}</div>
<footer><span>source: data/interim/event_*_framing.jsonl</span><span>stance clipped to −2…+2</span><span>shares within media group</span></footer>
</div>'''
OUT.write_text(HTML,encoding="utf-8")
print("wrote",OUT,len(HTML),"bytes")
