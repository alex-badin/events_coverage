#!/usr/bin/env python3
"""Cluster problem_definition & causal-claim per event; export assignments + render report."""
import numpy as np, collections, html, csv
from pathlib import Path
import cluster_lib as C
ROOT=Path("/Users/alexbadin/GitHub/_projects/events_coverage")
SP=Path("/Users/alexbadin/GitHub/_projects/events_coverage/data/interim/framing_embeddings")
OUT=ROOT/"reports"/"cluster_report.html"
CSVDIR=ROOT/"reports"/"clusters"; CSVDIR.mkdir(parents=True,exist_ok=True)
SHORT={"Federal TV and state broadcasters":"fedTV","Independent and exile media":"indep","Mainstream business and general media":"biz","War and military channels":"war","State agencies":"state","Pro-government online media":"progov"}
GORDER=["state","progov","fedTV","biz","war","indep"]
FIELD_LBL={"problem_definition":"PROBLEM DEFINITION — what the event <i>is</i> (Entman 1)",
           "causal":"CAUSAL ATTRIBUTION — who/what caused it + how (Entman 2)",
           "treatment":"TREATMENT — the prescribed remedy / response (Entman 4)"}
EVENT_LBL={"kursk_2025w11":"Kursk / Sudzha","trump_zelensky_2025w10":"Trump–Zelensky in Washington"}
READING={
 ("kursk_2025w11","causal"):"Three causal stories. <b>Independent/exile is the most agentive toward Russia</b> — 55% of its causal claims name <i>Russian forces' pipeline maneuver</i> as the cause, vs business at 32%, which instead leans hardest (62%) on <i>Ukraine's invasion/occupation</i> as the cause.",
 ("kursk_2025w11","problem_definition"):"Eight facets of one shared story. The official <b>“liberation of settlements”</b> framing is a federal-TV/state register (fedTV 23%, war 2%, independent 5%); independent over-indexes the neutral <b>civilian-evacuation</b> and generic-operation facets.",
 ("trump_zelensky_2025w10","causal"):"The clearest divergence in either event. <b>Pro-gov 60% / war 56% / state 52% pin the breakdown on Zelensky</b> (“didn’t want peace, was disrespectful”); <b>independent only 36%</b>, spreading cause across Trump and a mutual altercation.",
 ("trump_zelensky_2025w10","problem_definition"):"One dominant frame — a <b>failed, confrontational meeting</b> (56–75% everywhere). Federal TV leans more on the <b>aid-halt aftermath</b> (34%); independent holds a small distinct <b>“diplomatic failure”</b> cluster (19%) that war channels never use (0%).",
 ("kursk_2025w11","treatment"):"Three prescriptions. <b>“Continue the offensive”</b> dominates every group (62–74%) <b>except independent/exile (31%)</b>, whose ‘remedy’ is mostly informational (links to Operation Potok details, 44%) or civilian-evacuation — independent reports rather than prescribes. (χ² V=0.20, significant.)",
 ("trump_zelensky_2025w10","treatment"):"Remedies fragment (n=114, k high, low silhouette). The recurring prescription across pro-gov/state is <b>Zelensky should concede</b> (apologize, stop criticizing Putin, return ‘when ready for peace’); federal TV leans to <b>halt/condition US aid</b>; independent skews informational. Not statistically separable at this sample size.",
}
SETS=[("kursk_2025w11","problem_definition"),("kursk_2025w11","causal"),("kursk_2025w11","treatment"),
      ("trump_zelensky_2025w10","problem_definition"),("trump_zelensky_2025w10","causal"),("trump_zelensky_2025w10","treatment")]

def shade(p):  # within-group % -> indigo bg
    a=min(0.82,p/100*1.15); tc="#fff" if p>=42 else "var(--ink)"
    return f"background:rgba(46,58,102,{a:.3f});color:{tc}"

SECTIONS=[]; NAV=[]
for slug,field in SETS:
    X,texts,groups,sources,causes,ids=C.load(slug,field)
    Xn=C.l2(X)
    hi=min(12,max(4,len(texts)//22))
    k,sil,labels=C.pick_k_kmeans(Xn,3,hi)
    g=[SHORT.get(x,x) for x in groups]; gtot=collections.Counter(g)
    bigG=[x for x in GORDER if gtot.get(x,0)>=15]
    # export full assignments
    with open(CSVDIR/f"{slug}_{field}_clusters.csv","w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["cluster","message_id","source","media_group","cause_entity","value"])
        for i in range(len(texts)):
            w.writerow([int(labels[i]),ids[i],sources[i],groups[i],causes[i],texts[i]])
    anchor=f"{slug}_{field}"; NAV.append((EVENT_LBL[slug],field,anchor,len(texts),k))
    cards=""
    for lab,n in collections.Counter(labels).most_common():
        idxs=np.where(labels==lab)[0]
        sub=Xn[idxs]; c=sub.mean(0); c/=np.linalg.norm(c)+1e-9
        order=idxs[np.argsort(-(sub@c))]
        med=order[0]; terms=C.top_terms([str(texts[i]) for i in idxs],5)
        # cross-media cells
        cells=""
        for x in bigG:
            gi=sum(1 for i in idxs if g[i]==x); p=round(100*gi/gtot[x]) if gtot[x] else 0
            cells+=f'<td class="hm" style="{shade(p)}">{p}<span class="pct">%</span></td>'
        blame=""
        if field=="causal":
            cc=collections.Counter(str(causes[i]) for i in idxs if causes[i] and causes[i]!='None')
            blame='<div class="blame">blamed: '+", ".join(f'{html.escape(e)} <b>{n2}</b>' for e,n2 in cc.most_common(3))+'</div>'
        reps="".join(f'<li>{html.escape(str(texts[i]))}</li>' for i in order[:10])
        more=""
        if n>10:
            allm="".join(f'<li>{html.escape(str(texts[i]))}</li>' for i in order[10:])
            more=f'<details><summary>show all {n}</summary><ul class="mem">{allm}</ul></details>'
        terms_html="".join(f'<span class="term">{html.escape(t)}</span>' for t in terms)
        cards+=f'''<div class="cl">
          <div class="clh"><span class="sz">{n}</span><div class="terms">{terms_html}</div>
            <table class="hmrow"><tr>{cells}</tr></table></div>
          <div class="med">“{html.escape(str(texts[med]))}”</div>{blame}
          <ul class="mem">{reps}</ul>{more}</div>'''
    gh="".join(f'<th>{x}</th>' for x in bigG)
    SECTIONS.append(f'''<section id="{anchor}">
      <div class="sech"><span class="ev">{html.escape(EVENT_LBL[slug])}</span><h2>{FIELD_LBL[field]}</h2>
        <span class="meta">{len(texts)} values · {k} clusters · KMeans/cosine · sil {sil:.2f}</span></div>
      <div class="reading">{READING.get((slug,field),"")}</div>
      <div class="hmkey">cells = <b>within-group %</b> (share of each group's values falling in that cluster) &nbsp;·&nbsp; columns: <table class="hmrow inline"><tr>{gh}</tr></table></div>
      {cards}</section>''')

navhtml="".join(f'<a href="#{a}"><span class="k">{html.escape(EVENT_LBL[s] if False else l)}</span><span>{f}</span><span class="nn">{n} · k={k}</span></a>' for l,f,a,n,k in NAV)

HTML=f'''<title>Framing clusters — problem definition & causal attribution</title>
<meta name="description" content="KMeans clustering of the unique problem_definition and causal_attribution values for Kursk and Trump-Zelensky, with cross-media distribution and full members.">
<style>
:root{{--ground:#E7EAEE;--card:#FCFDFE;--rule:#D3D8DF;--rule2:#E6E9ED;--ink:#161A21;--ink2:#4C5563;--ink3:#828B97;
--accent:#2E3A66;--accent2:#4A5891;--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;}}
*{{box-sizing:border-box}}body{{margin:0}}
.page{{background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.5;padding:0 clamp(12px,3vw,40px) 80px}}
.eyebrow{{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent2);font-weight:600}}
header.mast{{max-width:1080px;margin:0 auto;padding:clamp(28px,5vw,52px) 0 14px}}
.mast h1{{font-family:var(--mono);font-weight:680;letter-spacing:-.02em;font-size:clamp(1.6rem,3.6vw,2.5rem);margin:.4rem 0 0}}
.mast p{{color:var(--ink2);max-width:74ch;margin:.8rem 0 0;font-size:.98rem}}
.mast code{{font-family:var(--mono);background:var(--rule2);padding:.05em .35em;border-radius:2px;font-size:.85em}}
nav.evnav{{max-width:1080px;margin:1.3rem auto 0;display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}
nav.evnav a{{text-decoration:none;background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.6rem .7rem;display:flex;flex-direction:column;gap:.12rem;border-left:3px solid var(--accent)}}
nav.evnav a:hover{{background:#fff}} nav.evnav .k{{font-weight:600;font-size:.86rem;color:var(--ink)}}
nav.evnav a>span:nth-child(2){{font-family:var(--mono);font-size:.74rem;color:var(--accent2)}}
nav.evnav .nn{{font-family:var(--mono);font-size:.7rem;color:var(--ink3)}}
.wrap{{max-width:1080px;margin:0 auto}}
section{{margin-top:clamp(34px,5vw,54px);scroll-margin-top:14px}}
.sech{{display:flex;align-items:baseline;gap:.7rem;border-bottom:1.5px solid var(--ink);padding-bottom:.5rem;flex-wrap:wrap}}
.sech .ev{{font-family:var(--mono);font-size:.66rem;letter-spacing:.12em;text-transform:uppercase;color:#fff;background:var(--accent);padding:.2rem .5rem;border-radius:2px}}
.sech h2{{font-size:1.05rem;margin:0;font-weight:600;font-family:var(--mono);letter-spacing:.01em}}
.sech .meta{{margin-left:auto;font-family:var(--mono);font-size:.73rem;color:var(--ink3)}}
.reading{{background:#F0F2F6;border:1px solid var(--rule);border-left:3px solid var(--accent2);border-radius:6px;padding:.7rem .9rem;margin:.9rem 0;font-size:.92rem;color:var(--ink2)}}
.reading b{{color:var(--ink)}}
.hmkey{{font-family:var(--mono);font-size:.72rem;color:var(--ink3);margin:.3rem 0 1rem;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}}
.hmrow{{border-collapse:collapse}} .hmrow.inline{{display:inline-table;vertical-align:middle}}
.hmrow th{{font-family:var(--mono);font-size:.62rem;color:var(--ink3);padding:.1rem .3rem;text-transform:uppercase;font-weight:600;text-align:center;border:1px solid var(--rule2)}}
td.hm{{font-family:var(--mono);font-size:.74rem;text-align:center;padding:.22rem .35rem;border:1px solid var(--rule2);min-width:34px;font-variant-numeric:tabular-nums}}
td.hm .pct{{font-size:.7em;opacity:.6}}
.cl{{background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:.8rem .95rem;margin-top:11px}}
.clh{{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap}}
.sz{{font-family:var(--mono);font-weight:680;font-size:1.1rem;color:var(--accent);min-width:2.2ch;text-align:right}}
.terms{{display:flex;flex-wrap:wrap;gap:.25rem;flex:1;min-width:120px}}
.term{{font-family:var(--mono);font-size:.72rem;background:var(--rule2);border-radius:3px;padding:.1rem .4rem;color:var(--ink2)}}
.clh .hmrow{{margin-left:auto}}
.med{{font-size:.92rem;color:var(--ink);margin:.55rem 0 .3rem;font-style:italic}}
.blame{{font-family:var(--mono);font-size:.76rem;color:var(--ink2);margin:.1rem 0 .4rem}}
.blame b{{color:var(--accent)}}
ul.mem{{margin:.3rem 0 0;padding-left:1.1rem;color:var(--ink2);font-size:.85rem}}
ul.mem li{{margin:.12rem 0}}
details{{margin-top:.35rem}} summary{{font-family:var(--mono);font-size:.74rem;color:var(--accent2);cursor:pointer}}
footer{{max-width:1080px;margin:50px auto 0;padding-top:16px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:.74rem;color:var(--ink3)}}
@media(max-width:720px){{nav.evnav{{grid-template-columns:1fr 1fr}}.clh .hmrow{{margin-left:0;width:100%}}}}
</style>
<div class="page">
<header class="mast">
<div class="eyebrow">events_coverage · structuring the free-text framings</div>
<h1>Framing clusters</h1>
<p>The two content fields with the richest values — <code>problem_definition</code> and <code>causal_attribution</code> — are ~97% unique, so they were embedded (OpenAI <code>text-embedding-3-large</code>) and clustered (KMeans, k chosen by cosine silhouette over 3–12). Each cluster shows its size, top terms, the most-central member (medoid), the <b>cross-media distribution</b>, and — click <i>show all</i> — every member. Full assignments are exported to <code>reports/clusters/*.csv</code>.</p>
</header>
<nav class="evnav">{navhtml}</nav>
<div class="wrap">{''.join(SECTIONS)}</div>
<footer>embeddings: text-embedding-3-large · clustering: KMeans on L2-normalized vectors, silhouette-selected k · medoid = nearest to cluster centroid · within-group % = share of that group's values in the cluster</footer>
</div>'''
OUT.write_text(HTML,encoding="utf-8")
print("wrote",OUT,f"{len(HTML)/1024:.0f} KB")
print("CSVs ->",CSVDIR)
