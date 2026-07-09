#!/usr/bin/env python3
"""Association report: every aggregatable framing dimension × media group, with chi2 / Cramer's V."""
import numpy as np, html
from pathlib import Path
import stats_lib as S
OUT=Path("/Users/alexbadin/GitHub/_projects/events_coverage/reports/association_report.html")
EVENT_LBL={"kursk_2025w11":"Kursk / Sudzha","trump_zelensky_2025w10":"Trump–Zelensky in Washington"}

def sig_stars(p): return "***" if p<.001 else "**" if p<.01 else "*" if p<.05 else "ns"
def vcell(v):
    a=min(0.85,v/0.4*0.85); tc="#fff" if v>=0.2 else "var(--ink)"
    return f'style="background:rgba(46,58,102,{a:.3f});color:{tc}"'
def pctshade(p):
    a=min(0.82,p/100*1.1); tc="#fff" if p>=46 else "var(--ink)"
    return f"background:rgba(46,58,102,{a:.3f});color:{tc}"

def build_event(slug):
    dims=S.dimensions(slug)
    tested=[]
    for d in dims:
        res=S.test(d["table"],d["G"])
        if res: tested.append((d,res))
    pv=S.holm([res["p"] for _,res in tested])
    order=sorted(range(len(tested)),key=lambda i:-tested[i][1]["v"])
    # leaderboard
    lb='<table class="lead"><thead><tr><th>dimension</th><th>unit</th><th>n</th><th>χ²</th><th>dof</th><th>p (raw)</th><th>p (Holm)</th><th>Cramér&#39;s V</th><th>flags</th></tr></thead><tbody>'
    for i in order:
        d,res=tested[i]; holmp=pv[i]; stars=sig_stars(holmp)
        flag=""
        if res["pct_lt5"]>0.2: flag=f'<span class="warn">⚠ {res["pct_lt5"]*100:.0f}% cells exp&lt;5</span>'
        scls="sig3" if holmp<.001 else "sig2" if holmp<.01 else "sig1" if holmp<.05 else "nsig"
        barw=min(100,res["v"]/0.4*100)
        lb+=(f'<tr><td class="dim">{html.escape(d["name"])}</td><td class="u">{html.escape(d["unit"])}</td>'
             f'<td class="num">{res["n"]}</td><td class="num">{res["chi2"]:.1f}</td><td class="num">{res["dof"]}</td>'
             f'<td class="num">{res["p"]:.1e}</td><td class="num {scls}">{holmp:.1e} {stars}</td>'
             f'<td class="vc"><span class="vbar" style="width:{barw:.0f}%"></span><span class="vval">{res["v"]:.2f}</span></td>'
             f'<td class="fl">{flag}</td></tr>')
    lb+='</tbody></table>'
    # detail tables (ordered by V)
    details=""
    for i in order:
        d,res=tested[i]; holmp=pv[i]
        cols=res["cols"]; M=res["M"]; cats=res["cats"]
        colsum=M.sum(0); colsum[colsum==0]=1
        head="".join(f'<th>{c}<span class="cn">n={int(M[:,j].sum())}</span></th>' for j,c in enumerate(cols))
        rows=""
        # order rows by total desc
        rorder=sorted(range(len(cats)),key=lambda r:-M[r].sum())
        for r in rorder:
            cells=""
            for j in range(len(cols)):
                p=100*M[r,j]/colsum[j]
                cells+=f'<td class="hm" style="{pctshade(p)}">{p:.0f}</td>'
            rows+=f'<tr><td class="rl">{html.escape(str(cats[r]))}</td>{cells}</tr>'
        stars=sig_stars(holmp)
        note=f' · {html.escape(d["note"])}' if d["note"] else ''
        flag=f' · ⚠ {res["pct_lt5"]*100:.0f}% of cells have expected&lt;5 (χ² approximate)' if res["pct_lt5"]>0.2 else ''
        details+=(f'<div class="det"><div class="deth"><h4>{html.escape(d["name"])}</h4>'
                  f'<span class="stat">V={res["v"]:.2f} · χ²({res["dof"]})={res["chi2"]:.1f} · p<sub>Holm</sub>={holmp:.1e} <b class="{("sig" if holmp<.05 else "ns")}">{stars}</b></span></div>'
                  f'<div class="cap">columns = media groups · cells = <b>% within that group</b> (column sums to 100) · unit: {html.escape(d["unit"])}{note}{flag}</div>'
                  f'<div class="tw"><table class="ct"><thead><tr><th class="rl">{html.escape(d["name"])}</th>{head}</tr></thead><tbody>{rows}</tbody></table></div></div>')
    nsig=sum(1 for i in range(len(tested)) if pv[i]<.05)
    return tested,nsig,lb,details

S1=build_event("kursk_2025w11"); S2=build_event("trump_zelensky_2025w10")
def section(slug,packed):
    tested,nsig,lb,details=packed
    return (f'<section id="{slug}"><div class="sech"><h2>{html.escape(EVENT_LBL[slug])}</h2>'
            f'<span class="meta">{len(tested)} dimensions · {nsig} significant after Holm · groups with n≥15</span></div>'
            f'<h3 class="bh">Association leaderboard <span class="sub">— ranked by effect size (Cramér&#39;s V)</span></h3>{lb}'
            f'<h3 class="bh">Every dimension × media group <span class="sub">— within-group % (read down a column for that outlet&#39;s profile)</span></h3>{details}</section>')

HTML=f'''<title>Framing × media type — association tests</title>
<meta name="description" content="Every aggregatable framing dimension cross-tabulated against media group, with chi-square / Cramer's V association tests, for Kursk and Trump-Zelensky.">
<style>
:root{{--ground:#E7EAEE;--card:#FCFDFE;--rule:#D3D8DF;--rule2:#E6E9ED;--ink:#161A21;--ink2:#4C5563;--ink3:#828B97;
--accent:#2E3A66;--accent2:#4A5891;--pos:#2C7A68;--neg:#B14E2C;--warn:#9C6B14;--warnbg:#F5EDD8;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;}}
*{{box-sizing:border-box}}body{{margin:0}}
.page{{background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.5;padding:0 clamp(12px,3vw,40px) 80px}}
.eyebrow{{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent2);font-weight:600}}
header.mast{{max-width:1120px;margin:0 auto;padding:clamp(28px,5vw,52px) 0 14px}}
.mast h1{{font-family:var(--mono);font-weight:680;letter-spacing:-.02em;font-size:clamp(1.6rem,3.6vw,2.5rem);margin:.4rem 0 0}}
.mast p{{color:var(--ink2);max-width:76ch;margin:.8rem 0 0;font-size:.98rem}}
.mast code{{font-family:var(--mono);background:var(--rule2);padding:.05em .35em;border-radius:2px;font-size:.85em}}
.caveat{{background:var(--warnbg);border:1px solid #E4D2A6;border-radius:6px;padding:.7rem .95rem;margin:1.1rem 0 0;max-width:88ch;font-size:.86rem;color:#5e4410}}
.caveat b{{color:#43320c}} .caveat ul{{margin:.4rem 0 0;padding-left:1.1rem}} .caveat li{{margin:.15rem 0}}
.key{{display:flex;flex-wrap:wrap;gap:.4rem 1.3rem;margin:.9rem 0 0;font-family:var(--mono);font-size:.73rem;color:var(--ink2)}}
nav.evnav{{max-width:1120px;margin:1.2rem auto 0;display:grid;grid-template-columns:1fr 1fr;gap:9px}}
nav.evnav a{{text-decoration:none;background:var(--card);border:1px solid var(--rule);border-radius:6px;padding:.6rem .8rem;border-left:3px solid var(--accent);font-weight:600;color:var(--ink)}}
.wrap{{max-width:1120px;margin:0 auto}}
section{{margin-top:clamp(34px,5vw,52px);scroll-margin-top:14px}}
.sech{{display:flex;align-items:baseline;gap:.7rem;border-bottom:1.5px solid var(--ink);padding-bottom:.5rem;flex-wrap:wrap}}
.sech h2{{font-size:1.3rem;margin:0;font-weight:650}}
.sech .meta{{margin-left:auto;font-family:var(--mono);font-size:.74rem;color:var(--ink3)}}
.bh{{font-family:var(--mono);font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink2);margin:1.6rem 0 .6rem;font-weight:600}}
.bh .sub{{text-transform:none;letter-spacing:0;color:var(--ink3);font-weight:400}}
.tw,.lead{{overflow-x:auto}}
table{{border-collapse:collapse;background:var(--card)}}
table.lead{{width:100%;border:1px solid var(--rule);border-radius:6px;font-size:.83rem}}
.lead th{{text-align:right;font-family:var(--mono);font-size:.66rem;text-transform:uppercase;letter-spacing:.04em;color:var(--ink3);padding:.5rem .55rem;border-bottom:1px solid var(--rule);background:#EFF1F4;font-weight:600}}
.lead th:first-child{{text-align:left}}
.lead td{{padding:.4rem .55rem;border-bottom:1px solid var(--rule2);text-align:right;font-variant-numeric:tabular-nums}}
.lead td.dim{{text-align:left;font-weight:600}} .lead td.u{{text-align:left;font-family:var(--mono);font-size:.74rem;color:var(--ink3)}}
.lead td.num{{font-family:var(--mono);font-size:.78rem}}
.sig3{{color:var(--pos);font-weight:700}}.sig2{{color:var(--pos);font-weight:600}}.sig1{{color:var(--accent2);font-weight:600}}.nsig{{color:var(--ink3)}}
.vc{{position:relative;min-width:90px}}
.vbar{{display:inline-block;height:.62rem;background:var(--accent);border-radius:1px;vertical-align:middle;margin-right:.4rem}}
.vval{{font-family:var(--mono);font-weight:600}}
td.fl{{text-align:left}} .warn{{font-family:var(--mono);font-size:.7rem;color:var(--warn)}}
.det{{margin-top:1rem;background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:.7rem .85rem}}
.deth{{display:flex;align-items:baseline;gap:.7rem;flex-wrap:wrap}}
.deth h4{{margin:0;font-size:.98rem;font-family:var(--mono)}}
.deth .stat{{margin-left:auto;font-family:var(--mono);font-size:.76rem;color:var(--ink2)}}
.deth .stat b.sig{{color:var(--pos)}} .deth .stat b.ns{{color:var(--ink3)}}
.cap{{font-size:.78rem;color:var(--ink3);margin:.25rem 0 .5rem}}
table.ct{{font-size:.82rem;border:1px solid var(--rule2);border-radius:5px}}
table.ct th{{font-family:var(--mono);font-size:.68rem;color:var(--ink3);padding:.3rem .5rem;border-bottom:1px solid var(--rule2);text-align:center;text-transform:uppercase}}
table.ct th.rl{{text-align:left;color:var(--ink2)}}
.ct .cn{{display:block;font-weight:400;font-size:.62rem;color:var(--ink3)}}
td.rl{{text-align:left;padding:.3rem .55rem;border-bottom:1px solid var(--rule2);white-space:nowrap;font-size:.82rem}}
td.hm{{text-align:center;padding:.3rem .5rem;border-bottom:1px solid var(--rule2);border-left:1px solid var(--rule2);font-family:var(--mono);font-size:.78rem;font-variant-numeric:tabular-nums;min-width:40px}}
footer{{max-width:1120px;margin:50px auto 0;padding-top:16px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:.74rem;color:var(--ink3)}}
@media(max-width:720px){{nav.evnav{{grid-template-columns:1fr}}}}
</style>
<div class="page">
<header class="mast">
<div class="eyebrow">events_coverage · do framings differ by media type?</div>
<h1>Framing × media type — association tests</h1>
<p>Every aggregatable framing dimension — clusters (problem / causal / treatment), the cast of actors, role types, action-label valence, epistemic stance, Semetko frames — cross-tabulated against media group, with a <b>χ² test of independence</b> and <b>Cramér&#39;s V</b> effect size. The leaderboard ranks dimensions by how strongly they separate outlets; every dimension is then shown as a within-group % table.</p>
<div class="caveat"><b>Read the statistics with these caveats:</b>
<ul>
<li><b>Effect size (V)</b> matters more than p here: ≈0.1 small, 0.2 moderate, ≥0.3 large. p just says "not zero," and large n makes tiny differences "significant."</li>
<li><b>p (Holm)</b> is corrected for the ~15 tests per event. Stars use the corrected value.</li>
<li><b>Pseudo-replication:</b> role/valence units are per-annotation (a message contributes several), which violates independence and <i>inflates</i> χ². Message-level dims (epistemic, clusters, remedy, frames) are clean; treat annotation-level V as the more reliable signal there.</li>
<li><b>⚠ flag:</b> many cells have expected count &lt;5 (sparse roles/small groups) — χ² is approximate there; lean on V.</li>
<li>Trump–Zelensky has n=185, so it is <b>underpowered</b>: moderate effects may not reach significance.</li>
</ul></div>
</header>
<nav class="evnav"><a href="#kursk_2025w11">Kursk / Sudzha</a><a href="#trump_zelensky_2025w10">Trump–Zelensky in Washington</a></nav>
<div class="wrap">{section("kursk_2025w11",S1)}{section("trump_zelensky_2025w10",S2)}</div>
<footer>χ² via scipy.stats.chi2_contingency · Cramér&#39;s V = √(χ²/(n·(min(r,c)−1))) · Holm–Bonferroni across dimensions per event · clusters: text-embedding-3-large + KMeans</footer>
</div>'''
OUT.write_text(HTML,encoding="utf-8")
print("wrote",OUT,f"{len(HTML)/1024:.0f} KB")
