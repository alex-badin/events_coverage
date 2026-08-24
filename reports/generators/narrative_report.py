#!/usr/bin/env python3
"""Narrative-content report: WHO is cast as what, and WHAT story each media group tells.
Surfaces Entman's content fields (roles->actors, problem_definition, causal_attribution,
treatment) per media group, per event — the complement to the presentational grid."""
import json, collections, statistics, html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"reports"/"narrative_report.html"

EVENTS=[("Kursk / Sudzha","war · contested","kursk_2025w11"),
        ("Trump–Zelensky in Washington","diplomacy · clash","trump_zelensky_2025w10"),
        ("Putin–Trump phone call","diplomacy · thaw","putin_trump_call_2025w08"),
        ("US–Russia contacts","diplomacy · thaw","us_russia_contacts_2025w09")]

SHORT={"Pro-government online media":"Pro-gov online","Federal TV and state broadcasters":"Federal TV",
       "Mainstream business and general media":"Business/general","State agencies":"State agencies",
       "Independent and exile media":"Independent/exile","War and military channels":"War channels"}
ORDER=["State agencies","Federal TV and state broadcasters","Pro-government online media",
       "Mainstream business and general media","War and military channels","Independent and exile media"]
APPROVING={"liberator","hero","defender","protector","ally","beneficiary","mediator"}
CONDEMNING={"aggressor","occupier","villain","threat","perpetrator","provocateur","traitor"}
CAT_ORDER=[("approve","cast favourably","var(--pos)"),("amb","cast as victim","var(--amb)"),
           ("condemn","cast unfavourably","var(--neg)"),("neut","cast as neutral / other","var(--neu)")]
READINGS={
 "kursk_2025w11":"<b>Roles diverge sharply; the storyline does not.</b> Russian forces are <span class='hp'>liberator / hero</span> to every state-aligned outlet (stance +1.0 … +1.3) but flatten to <span class='hn'>neutral / aggressor</span> for independent &amp; exile media (+0.07). Yet all six outlets define the event with the same factual gloss (“Russia regained Sudzha”) and prescribe the same remedy (“continue the offensive”) — independent coverage here mostly <i>relays</i> the operation rather than counter-framing it. The evaluative split lives in the <b>roles</b>, not the problem definition.",
 "trump_zelensky_2025w10":"<b>The clearest narrative fork.</b> Zelensky is a <span class='hn'>provocateur</span> to all (a Russian-media corpus) — but on a gradient: hostile in war channels (−1.45), far softer for independent media (−0.64). Blame is allocated differently in the problem definition (pro-gov: “Zelensky’s disrespectful behaviour”; business: “Trump pressures Zelensky”; independent: a neutral “heated dispute”), and the remedies fork — pro-gov &amp; war channels want Zelensky to capitulate, federal TV wants the West to “stop financing the conflict.”",
 "putin_trump_call_2025w08":"<b>Convergence, not divergence.</b> Every outlet casts the actors as <span class='hu'>neutral</span> and tells the same procedural story — negotiations in Riyadh, prepare a Putin–Trump meeting. No contested actors. When Russian media broadly welcome an event, the narrative layer agrees across the spectrum and the instrument correctly shows little to separate.",
 "us_russia_contacts_2025w09":"<b>Convergence again.</b> Actors stay <span class='hu'>neutral</span> across the board and the storyline is uniformly procedural (continuing contacts, a planned Witkoff–Putin meeting). The only faint colour is pro-gov / federal TV casting Putin as <span class='hp'>protector / mediator</span> — a mild warm tint, not a contested role.",
}
MINN=15
def clip(p): return max(-2,min(2,p)) if isinstance(p,(int,float)) else None
def load(slug): return [r for r in (json.loads(l) for l in open(ROOT/f"data/interim/event_{slug}_framing.jsonl",encoding="utf-8")) if r.get("on_event",True)]

def medoid(texts, k=1, lo=24, hi=170):
    """Most typical distinct quote(s) by word-overlap — avoids cherry-picking."""
    seen={};
    for t in texts:
        t=(t or "").strip()
        if lo<=len(t)<=hi and t.lower() not in seen: seen[t.lower()]=t
    cand=list(seen.values())
    if len(cand)<=k: return cand
    ws=[set(c.lower().split()) for c in cand]
    def sim(a,b): return len(a&b)/len(a|b) if (a|b) else 0
    scored=sorted(cand, key=lambda c: -sum(sim(ws[cand.index(c)],w) for w in ws))
    return scored[:k]

def role_cat(role):
    return "approve" if role in APPROVING else "condemn" if role in CONDEMNING else "amb" if role=="victim" else "neut"

SECTIONS=[]; NAV=[]
for ev_label, ev_kind, slug in EVENTS:
    R=load(slug)
    Gc=collections.Counter(r["media_group"] for r in R)
    groups=[g for g in ORDER if Gc.get(g,0)>=MINN]
    short=lambda g:SHORT.get(g,g)
    anchor=slug
    NAV.append((ev_label,ev_kind,anchor,len(R),len(groups)))

    # ---- A. cast-of-actors matrix ----
    # entity -> per group: (mean polarity, n, [top roles])
    def cell_for(e,g):
        roles=collections.Counter(); pols=[]
        for r in R:
            if r["media_group"]!=g: continue
            for m in r.get("moral_evaluation") or []:
                if m.get("entity")==e:
                    if m.get("role"): roles[m["role"]]+=1
                    p=clip(m.get("polarity"))
                    if p is not None: pols.append(p)
        if len(pols)<2: return None
        return (statistics.mean(pols), len(pols), roles.most_common(3))
    ment=collections.Counter(m["entity"] for r in R for m in (r.get("moral_evaluation") or []) if m.get("entity"))
    ents=[]
    for e,_ in ment.most_common(20):
        cov=sum(1 for g in groups if cell_for(e,g))
        if cov>=max(3,len(groups)//2): ents.append(e)
        if len(ents)>=7: break

    def matrix_html():
        h='<div class="tblwrap"><table class="mtx"><thead><tr><th class="rowhdr">actor</th>'
        for g in groups:
            thin=' thin' if Gc[g]<MINN else ''
            h+=f'<th class="{thin}">{html.escape(short(g))}</th>'
        h+='</tr></thead><tbody>'
        for e in ents:
            cells=[]; cats=set()
            for g in groups:
                c=cell_for(e,g)
                if not c: cells.append('<td class="na">·</td>'); continue
                pol,n,tr=c
                if pol>=0: a=min(.8,pol/2*.85); bg=f"rgba(44,122,104,{a:.3f})"
                else: a=min(.8,-pol/2*.85); bg=f"rgba(177,78,44,{a:.3f})"
                tc="#fff" if abs(pol)>=1.15 else "var(--ink)"
                top=tr[0][0]; cats.add(role_cat(top))
                roletxt=top
                if len(tr)>1 and tr[1][1]>=tr[0][1]*0.6 and role_cat(tr[1][0])!=role_cat(top):
                    roletxt=f"{top}<span class='r2'> / {tr[1][0]}</span>"
                cells.append(f'<td class="mc" style="background:{bg};color:{tc}"><span class="role">{roletxt}</span>'
                             f'<span class="pn">{pol:+.1f}<span class="nn2"> ·{n}</span></span></td>')
            flag=' <span class="flag">contested</span>' if len([c for c in cats if c!="neut"])>=2 or ("approve" in cats and "condemn" in cats) else ''
            h+=f'<tr><td class="el">{html.escape(e)}{flag}</td>'+''.join(cells)+'</tr>'
        h+='</tbody></table></div>'
        return h

    # ---- A2. roles -> which specific actors filled them (event-level) ----
    def roles_actors_html():
        byrole=collections.defaultdict(collections.Counter)
        for r in R:
            for m in r.get("moral_evaluation") or []:
                if m.get("role") and m.get("entity"): byrole[m["role"]][m["entity"]]+=1
        cols=''
        for cat,clabel,color in CAT_ORDER:
            roles_here=[(role,cnt) for role,cnt in byrole.items() if role_cat(role)==cat]
            roles_here.sort(key=lambda x:-sum(x[1].values()))
            if not roles_here: continue
            items=''
            for role,cnt in roles_here:
                actors=", ".join(html.escape(a) for a,_ in cnt.most_common(3))
                items+=f'<div class="ra"><span class="rn">{role}</span><span class="ras">{actors}</span></div>'
            cols+=f'<div class="racol"><div class="rahead" style="color:{color};border-color:{color}">{clabel}</div>{items}</div>'
        return f'<div class="rawrap">{cols}</div>'

    # ---- B. problem_definition per group ----
    def storyline_html():
        rows=''
        for g in groups:
            pds=[r.get("problem_definition") for r in R if r["media_group"]==g]
            m=medoid(pds,1)
            q=html.escape(m[0]) if m else "<span class='na'>—</span>"
            rows+=f'<div class="sl"><div class="slg">{html.escape(short(g))}</div><div class="slq">“{q}”</div></div>'
        return f'<div class="slwrap">{rows}</div>'

    # ---- C. blame + remedy ----
    def blame_remedy_html():
        rows=''
        for g in groups:
            cau=collections.Counter((r.get("causal_attribution") or {}).get("cause_entity")
                                    for r in R if r["media_group"]==g and (r.get("causal_attribution") or {}).get("cause_entity"))
            chips="".join(f'<span class="chip">{html.escape(e)}<span class="cc">{n}</span></span>' for e,n in cau.most_common(2)) or '<span class="na">—</span>'
            trs=[r.get("treatment") for r in R if r["media_group"]==g and r.get("treatment")]
            tn=len(trs); tot=sum(1 for r in R if r["media_group"]==g)
            m=medoid(trs,1)
            tq=f'“{html.escape(m[0])}”' if m else '<span class="na">no remedy prescribed</span>'
            rows+=(f'<tr><td class="brg">{html.escape(short(g))}</td>'
                   f'<td class="brc">{chips}</td>'
                   f'<td class="brt">{tq}<span class="trn">{tn}/{tot} prescribe</span></td></tr>')
        return ('<div class="tblwrap"><table class="br"><thead><tr><th class="rowhdr">media group</th>'
                '<th class="rowhdr">blames (cause_entity)</th><th class="rowhdr">prescribes (treatment)</th></tr></thead>'
                f'<tbody>{rows}</tbody></table></div>')

    reading=READINGS.get(slug,"")
    body=(f'<div class="reading">{reading}</div>'
          f'<div class="block"><h3>Cast of actors — who is cast as what</h3>'
          f'<p class="bsub">Each cell: the role an outlet most often assigns the actor, and its stance toward it '
          f'(−2 hostile … +2 warm; ·n = stance mentions). Colour = stance. A <b>contested</b> actor is cast in conflicting role types across outlets.</p>{matrix_html()}</div>'
          f'<div class="block"><h3>Roles → the specific actors who filled them</h3>'
          f'<p class="bsub">The abstract roles made concrete: the actual entities each role was assigned to in this event (top 3 by frequency, across all outlets).</p>{roles_actors_html()}</div>'
          f'<div class="block"><h3>What is this event? — problem definition</h3>'
          f'<p class="bsub">The most typical verbatim gloss each outlet gives for what the event <i>is</i> (Entman function 1).</p>{storyline_html()}</div>'
          f'<div class="block"><h3>Who is responsible, and what should happen — cause &amp; remedy</h3>'
          f'<p class="bsub">Most-named cause (function 2) and the typical prescribed response (function 4), per outlet.</p>{blame_remedy_html()}</div>')

    SECTIONS.append(f'<section id="{anchor}"><div class="evhead"><span class="evkind">{html.escape(ev_kind)}</span>'
                    f'<h2>{html.escape(ev_label)}</h2><span class="evn">{len(R)} messages · {len(groups)} groups</span></div>{body}</section>')

navhtml="".join(f'<a href="#{a}"><span class="k">{html.escape(k)}</span><span>{html.escape(l)}</span><span class="nn">{n} msgs · {b} groups</span></a>' for l,k,a,n,b in NAV)

HTML=f'''<title>The narrative report — actors & storylines by media group</title>
<meta name="description" content="WHO each media group casts as hero/villain/victim, and what story it tells (problem, blame, remedy) — Entman's content fields surfaced per outlet, across four 2025 events.">
<style>
:root{{--ground:#E7EAEE;--card:#FCFDFE;--rule:#D3D8DF;--rule2:#E6E9ED;--ink:#161A21;--ink2:#4C5563;--ink3:#828B97;
--accent:#2E3A66;--accent2:#4A5891;--pos:#2C7A68;--neg:#B14E2C;--amb:#9C6B14;--neu:#7E8693;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;}}
*{{box-sizing:border-box}}body{{margin:0}}
.page{{background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.55;padding:0 clamp(14px,3.5vw,44px) 90px}}
.tnum{{font-variant-numeric:tabular-nums}}
header.mast{{max-width:1180px;margin:0 auto;padding:clamp(34px,6vw,64px) 0 22px}}
.eyebrow{{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent2);font-weight:600}}
.mast h1{{font-family:var(--mono);font-weight:680;letter-spacing:-.02em;font-size:clamp(1.7rem,4vw,2.7rem);margin:.5rem 0 0;text-wrap:balance;max-width:20ch}}
.mast p.lede{{color:var(--ink2);max-width:66ch;margin:.9rem 0 0;font-size:1.03rem}}
.callout{{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--accent);border-radius:6px;padding:.85rem 1rem;margin:1.3rem 0 0;max-width:66ch;font-size:.92rem;color:var(--ink2)}}
.callout b{{color:var(--ink)}}
.legend{{display:flex;flex-wrap:wrap;gap:.5rem 1.4rem;margin:1.2rem 0 0;font-family:var(--mono);font-size:.75rem;color:var(--ink2)}}
.legend .li{{display:flex;align-items:center;gap:.45rem}}
.legend .sw{{width:1.5rem;height:.7rem;border-radius:2px;border:1px solid var(--rule)}}
nav.evnav{{max-width:1180px;margin:1.5rem auto 0;display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
nav.evnav a{{text-decoration:none;background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.7rem .85rem;display:flex;flex-direction:column;gap:.15rem;border-left:3px solid var(--accent)}}
nav.evnav a:hover{{background:#fff}}
nav.evnav .k{{font-family:var(--mono);font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;color:var(--accent2)}}
nav.evnav a>span:nth-child(2){{font-weight:600;font-size:.92rem;color:var(--ink)}}
nav.evnav .nn{{font-family:var(--mono);font-size:.7rem;color:var(--ink3)}}
.wrap{{max-width:1180px;margin:0 auto}}
section{{margin-top:clamp(40px,5vw,60px);scroll-margin-top:14px}}
.evhead{{display:flex;align-items:baseline;gap:.8rem;border-bottom:1.5px solid var(--ink);padding-bottom:.5rem;position:sticky;top:0;background:var(--ground);z-index:5}}
.evkind{{font-family:var(--mono);font-size:.66rem;letter-spacing:.12em;text-transform:uppercase;color:#fff;background:var(--accent);padding:.2rem .5rem;border-radius:2px;white-space:nowrap}}
.evhead h2{{font-size:1.3rem;margin:0;font-weight:650}}
.evhead .evn{{margin-left:auto;font-family:var(--mono);font-size:.76rem;color:var(--ink3);white-space:nowrap}}
.reading{{background:#F0F2F6;border:1px solid var(--rule);border-radius:6px;padding:.8rem 1rem;margin-top:1rem;font-size:.93rem;color:var(--ink2);line-height:1.5}}
.reading b{{color:var(--ink)}}
.hp{{color:var(--pos);font-weight:600}}.hn{{color:var(--neg);font-weight:600}}.hu{{color:var(--neu);font-weight:600}}
.rawrap{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}}
.racol{{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.6rem .75rem}}
.rahead{{font-family:var(--mono);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;font-weight:600;border-bottom:1.5px solid;padding-bottom:.3rem;margin-bottom:.45rem}}
.ra{{display:flex;gap:.5rem;align-items:baseline;padding:.18rem 0;border-top:1px solid var(--rule2)}}
.ra:first-of-type{{border-top:none}}
.rn{{font-family:var(--mono);font-size:.76rem;color:var(--ink);font-weight:600;min-width:84px}}
.ras{{font-size:.82rem;color:var(--ink2)}}
.block{{margin-top:1.8rem}}
.block h3{{font-family:var(--mono);font-size:.98rem;letter-spacing:.01em;margin:0;font-weight:600}}
.bsub{{color:var(--ink3);font-size:.85rem;margin:.25rem 0 .8rem;max-width:80ch}}
.tblwrap{{overflow-x:auto;border:1px solid var(--rule);border-radius:6px;background:var(--card)}}
table{{border-collapse:collapse;width:100%}}
table.mtx,table.br{{font-size:.86rem}}
thead th{{position:sticky;top:0;background:#EFF1F4;text-align:left;padding:.55rem .7rem;font-weight:600;font-size:.76rem;color:var(--ink2);border-bottom:1px solid var(--rule);vertical-align:bottom;white-space:nowrap}}
thead th.rowhdr{{font-family:var(--mono);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink3)}}
thead th.thin{{color:var(--ink3);font-style:italic}}
/* matrix */
td.el{{text-align:left;padding:.45rem .7rem;border-bottom:1px solid var(--rule2);white-space:nowrap;font-weight:600;font-size:.86rem}}
td.mc{{text-align:left;padding:.4rem .7rem;border-bottom:1px solid var(--rule2);border-left:1px solid var(--rule2);vertical-align:top;min-width:104px}}
td.mc .role{{display:block;font-size:.82rem;line-height:1.25}}
td.mc .r2{{opacity:.72;font-weight:400}}
td.mc .pn{{display:block;font-family:var(--mono);font-size:.72rem;opacity:.85;margin-top:.1rem}}
.nn2{{opacity:.6}}
.flag{{font-family:var(--mono);font-size:.6rem;text-transform:uppercase;letter-spacing:.06em;color:var(--neg);border:1px solid var(--neg);border-radius:2px;padding:.05rem .25rem;margin-left:.4rem;vertical-align:middle;font-weight:600}}
td.na{{text-align:center;color:var(--ink3);border-bottom:1px solid var(--rule2);border-left:1px solid var(--rule2)}}
/* storyline */
.slwrap{{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:10px}}
.sl{{background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.7rem .85rem;border-top:3px solid var(--accent2)}}
.slg{{font-family:var(--mono);font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--accent2);font-weight:600;margin-bottom:.3rem}}
.slq{{font-size:.88rem;color:var(--ink);line-height:1.4}}
/* blame+remedy */
table.br td{{border-bottom:1px solid var(--rule2);padding:.5rem .7rem;vertical-align:top}}
td.brg{{font-family:var(--mono);font-size:.78rem;color:var(--ink);font-weight:600;white-space:nowrap;border-right:1px solid var(--rule2)}}
td.brc{{white-space:nowrap;border-right:1px solid var(--rule2)}}
.chip{{display:inline-block;background:#EFF1F4;border:1px solid var(--rule);border-radius:3px;padding:.12rem .4rem;margin:.1rem .25rem .1rem 0;font-size:.78rem}}
.chip .cc{{font-family:var(--mono);color:var(--ink3);margin-left:.3rem;font-size:.9em}}
td.brt{{font-size:.85rem;color:var(--ink);max-width:430px}}
.trn{{display:block;font-family:var(--mono);font-size:.68rem;color:var(--ink3);margin-top:.2rem}}
.na{{color:var(--ink3)}}
footer{{max-width:1180px;margin:60px auto 0;padding-top:18px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:.75rem;color:var(--ink3);display:flex;flex-wrap:wrap;gap:.4rem 1.4rem}}
@media(max-width:760px){{nav.evnav{{grid-template-columns:1fr 1fr}}}}
</style>
<div class="page">
<header class="mast">
<div class="eyebrow">events_coverage · narrative content layer</div>
<h1>The narrative report</h1>
<p class="lede">Not <i>how confidently</i> each outlet speaks (that is the distributions grid) but <b>what story it tells</b>: who is cast as hero, villain or victim, what the event is said to <i>be</i>, who is blamed, and what should be done. These are Entman's four content functions, surfaced per media group — with the abstract roles attached to the <b>specific actors</b> who carried them.</p>
<div class="callout">The headline signal is a <b>contested actor</b>: the same entity cast in opposing roles by different outlets — e.g. Russian forces as <span style="color:var(--pos)">liberator</span> in state media but <span style="color:var(--neg)">aggressor</span> in independent media. Where every outlet agrees (the thaw events below), the actors collapse to <span style="color:var(--neu)">neutral</span> and the storylines converge — narrative divergence tracks how <i>contested</i> the event is, not its topic.</div>
<div class="callout" style="border-left-color:var(--amb)">One boundary to keep in mind: this is a <b>Russian-language corpus only</b> (state agencies → independent/exile). Even the independent end sits inside or adjacent to the Russian information space, so the divergence the instrument can see runs from <b>state-celebratory to independent-neutral</b> — the fully oppositional “Russia sabotages peace” framing of Western or Ukrainian media is outside this dataset and will not appear, however the fields are read.</div>
<div class="legend">
<span class="li"><span class="sw" style="background:rgba(177,78,44,.6)"></span>hostile stance</span>
<span class="li"><span class="sw" style="background:#EFF1F4"></span>neutral</span>
<span class="li"><span class="sw" style="background:rgba(44,122,104,.6)"></span>warm stance</span>
<span class="li"><span class="flag" style="position:static">contested</span> conflicting role types across outlets</span>
</div>
</header>
<nav class="evnav">{navhtml}</nav>
<div class="wrap">{''.join(SECTIONS)}</div>
<footer><span>source: data/interim/event_*_framing.jsonl</span><span>roles &amp; stance from moral_evaluation</span><span>quotes are the most-typical (medoid) verbatim gloss per group</span><span>stance clipped −2…+2</span></footer>
</div>'''
OUT.write_text(HTML,encoding="utf-8")
print("wrote",OUT,len(HTML),"bytes")
