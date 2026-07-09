#!/usr/bin/env python3
"""Raw-record explorer: every per-message gpt-5.5 framing record, nothing aggregated.
Shows text_used + entities + full Entman decomposition + evidence, filterable."""
import json, html
from pathlib import Path
ROOT=Path("/Users/alexbadin/GitHub/_projects/events_coverage")
OUT=Path("/Users/alexbadin/GitHub/_projects/events_coverage/reports/raw_records.html")
SHORT={"Pro-government online media":"Pro-gov","Federal TV and state broadcasters":"Federal TV",
       "Mainstream business and general media":"Business","State agencies":"State agencies",
       "Independent and exile media":"Independent/exile","War and military channels":"War channels"}
EVENTS=[("Trump–Zelensky in Washington","trump_zelensky_2025w10"),
        ("Kursk / Sudzha","kursk_2025w11")]

def slim(r):
    return {
        "id":r.get("message_id"),"src":r.get("source"),
        "grp":SHORT.get(r.get("media_group"),r.get("media_group")),
        "date":(r.get("date") or "")[:10],"epi":r.get("epistemic_status"),
        "on":r.get("on_event"),"rr":r.get("rerank_score"),
        "text":r.get("text_used") or "",
        "pd":r.get("problem_definition"),"pde":r.get("problem_definition_evidence"),
        "ca":r.get("causal_attribution") or {},
        "me":[{"e":m.get("entity"),"r":m.get("role"),"p":m.get("polarity"),
               "i":m.get("intensity"),"ev":m.get("evidence")} for m in (r.get("moral_evaluation") or [])],
        "tr":r.get("treatment"),
        "al":[{"t":a.get("term"),"v":a.get("valence"),"a":a.get("action"),"ev":a.get("evidence")} for a in (r.get("action_labels") or [])],
        "emp":r.get("emphasized") or [],
        "sem":[k for k,v in (r.get("semetko") or {}).items() if v],
        "ent":[{"m":e.get("mention"),"c":e.get("canonical"),"t":e.get("type")} for e in (r.get("entities") or [])],
    }

DATA={}
for label,slug in EVENTS:
    recs=[slim(json.loads(l)) for l in open(ROOT/f"data/interim/event_{slug}_framing.jsonl",encoding="utf-8")]
    DATA[slug]={"label":label,"records":recs}

payload=json.dumps(DATA,ensure_ascii=False).replace("</","<\\/")

HTML="""<title>Raw framing records — explorer</title>
<meta name="description" content="Every per-message gpt-5.5 framing record (text, entities, Entman decomposition, evidence) for two events — unaggregated, filterable.">
<style>
:root{--ground:#E7EAEE;--card:#FCFDFE;--rule:#D3D8DF;--rule2:#E6E9ED;--ink:#161A21;--ink2:#4C5563;--ink3:#828B97;
--accent:#2E3A66;--accent2:#4A5891;--pos:#2C7A68;--neg:#B14E2C;--amb:#9C6B14;--neu:#7E8693;
--posb:#DEEDE8;--negb:#F2E2DB;--neub:#E6E9ED;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;}
*{box-sizing:border-box}body{margin:0}
.page{background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.5;padding:0 clamp(12px,3vw,40px) 80px}
.eyebrow{font-family:var(--mono);font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent2);font-weight:600}
header.mast{max-width:1080px;margin:0 auto;padding:clamp(28px,5vw,52px) 0 14px}
.mast h1{font-family:var(--mono);font-weight:680;letter-spacing:-.02em;font-size:clamp(1.6rem,3.6vw,2.4rem);margin:.4rem 0 0}
.mast p{color:var(--ink2);max-width:70ch;margin:.8rem 0 0;font-size:.98rem}
.trace{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--amb);border-radius:6px;padding:.7rem .9rem;margin:1rem 0 0;max-width:78ch;font-size:.88rem;color:var(--ink2)}
.trace b{color:var(--ink)} .trace code{font-family:var(--mono);background:var(--neub);padding:.05em .35em;border-radius:2px;font-size:.85em}
.controls{position:sticky;top:0;z-index:10;background:var(--ground);max-width:1080px;margin:1.2rem auto 0;padding:.7rem 0;border-bottom:1px solid var(--rule);display:flex;flex-wrap:wrap;gap:.5rem .7rem;align-items:center}
.controls label{font-family:var(--mono);font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink3);margin-right:.2rem}
select,input{font-family:var(--sans);font-size:.85rem;padding:.34rem .5rem;border:1px solid var(--rule);border-radius:4px;background:var(--card);color:var(--ink)}
input[type=text]{min-width:150px}
.count{margin-left:auto;font-family:var(--mono);font-size:.78rem;color:var(--ink2)}
.wrap{max-width:1080px;margin:0 auto}
.rec{background:var(--card);border:1px solid var(--rule);border-radius:7px;padding:.9rem 1rem;margin-top:13px}
.rhead{display:flex;flex-wrap:wrap;gap:.4rem .6rem;align-items:center;font-family:var(--mono);font-size:.74rem;color:var(--ink3);border-bottom:1px solid var(--rule2);padding-bottom:.5rem}
.rhead .src{color:var(--ink);font-weight:600;font-size:.82rem}
.tag{font-size:.64rem;letter-spacing:.04em;text-transform:uppercase;padding:.12rem .4rem;border-radius:2px;font-weight:600;border:1px solid var(--rule)}
.tag.grp{background:var(--accent);color:#fff;border-color:var(--accent)}
.tag.epi{background:var(--neub);color:var(--ink2)}
.tag.off{background:var(--negb);color:#8a3a20}
.txt{font-size:.92rem;color:var(--ink);margin:.6rem 0 .2rem;white-space:pre-wrap;line-height:1.45;background:#FBFBF8;border:1px solid var(--rule2);border-radius:5px;padding:.6rem .75rem;max-height:230px;overflow:auto}
.txt .lbl{display:block;font-family:var(--mono);font-size:.64rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ink3);margin-bottom:.3rem}
.grid{display:grid;grid-template-columns:1fr;gap:.5rem;margin-top:.6rem}
.fld{border:1px solid var(--rule2);border-radius:5px;padding:.45rem .6rem}
.fld>.k{font-family:var(--mono);font-size:.64rem;text-transform:uppercase;letter-spacing:.07em;color:var(--accent2);font-weight:600;margin-bottom:.3rem}
.fld .v{font-size:.88rem;color:var(--ink)}
.ev{color:var(--ink3);font-style:italic;font-size:.83rem}
.ev::before{content:"“"} .ev::after{content:"”"}
table.me{width:100%;border-collapse:collapse;font-size:.83rem;margin-top:.1rem}
table.me th{text-align:left;font-family:var(--mono);font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;color:var(--ink3);padding:.2rem .4rem;border-bottom:1px solid var(--rule2);font-weight:600}
table.me td{padding:.28rem .4rem;border-bottom:1px solid var(--rule2);vertical-align:top}
.role{font-family:var(--mono);font-weight:600;font-size:.8rem}
.role.approve{color:var(--pos)} .role.condemn{color:var(--neg)} .role.amb{color:var(--amb)} .role.neut{color:var(--neu)}
.pol{font-family:var(--mono);font-weight:600} .pol.pos{color:var(--pos)} .pol.neg{color:var(--neg)} .pol.zero{color:var(--ink3)}
tr.hit{background:#FFF6E0}
.chips{display:flex;flex-wrap:wrap;gap:.25rem}
.chip{font-family:var(--mono);font-size:.74rem;background:var(--neub);border:1px solid var(--rule);border-radius:3px;padding:.1rem .4rem}
.chip.pos{background:var(--posb)} .chip.neg{background:var(--negb)}
.sem{display:inline-block;font-family:var(--mono);font-size:.72rem;background:var(--accent);color:#fff;border-radius:2px;padding:.08rem .35rem;margin:.1rem .2rem .1rem 0}
.empty{color:var(--ink3);font-size:.85rem;text-align:center;padding:2rem}
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
@media(max-width:680px){.cols2{grid-template-columns:1fr}}
footer{max-width:1080px;margin:50px auto 0;padding-top:16px;border-top:1px solid var(--rule);font-family:var(--mono);font-size:.74rem;color:var(--ink3)}
</style>
<div class="page">
<header class="mast">
<div class="eyebrow">events_coverage · raw gpt-5.5 framing output</div>
<h1>Raw framing records</h1>
<p>Every per-message record exactly as the model produced it — the <code>text_used</code> it read, the entities it found, and its full Entman decomposition with the verbatim <b>evidence</b> quote behind each judgement. Nothing is aggregated here. Use the filters to reach any cell from the reports; matching <code>moral_evaluation</code> rows are highlighted.</p>
<div class="trace"><b>Trace the two questioned values:</b> set <i>event = Trump–Zelensky, group = Independent/exile, entity = Zelensky, role = provocateur</i> → 11 rows, of which <b>8 are <code>epistemic = attributed</code></b> (the outlet <b>reporting Trump's words</b>), 2 asserted, 1 a rhetorical question — the label tracks the framing <i>present in the text</i>, mostly reported rather than endorsed. Or <i>event = Kursk, group = State agencies, entity = Ukrainian Armed Forces, role = victim</i> → 11 rows, <b>all non-positive</b> polarity (10× −1, 1× 0) with evidence about losses/encirclement: "victim" here is the <b>defeated enemy</b>, not a sympathetic one — which is why role must be read together with polarity.</div>
</header>
<div class="controls">
<span><label>event</label><select id="fEvent"></select></span>
<span><label>group</label><select id="fGroup"></select></span>
<span><label>entity</label><input type="text" id="fEntity" placeholder="e.g. Zelensky"></span>
<span><label>role</label><select id="fRole"></select></span>
<span><label>epistemic</label><select id="fEpi"></select></span>
<span class="count" id="count"></span>
</div>
<div class="wrap" id="out"></div>
<footer>source: data/interim/event_*_framing.jsonl · two events shown (Trump–Zelensky 185, Kursk 669) · run the local export for the other four</footer>
</div>
<script>
const DATA=__PAYLOAD__;
const APPROVE=new Set(["liberator","hero","defender","protector","ally","beneficiary","mediator"]);
const CONDEMN=new Set(["aggressor","occupier","villain","threat","perpetrator","provocateur","traitor"]);
function rcat(r){return APPROVE.has(r)?"approve":CONDEMN.has(r)?"condemn":r=="victim"?"amb":"neut";}
function esc(s){return (s==null?"":String(s)).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
const $=id=>document.getElementById(id);
function opts(sel,arr,all){sel.innerHTML="";const o=document.createElement("option");o.value="";o.textContent=all;sel.appendChild(o);
  arr.forEach(v=>{const e=document.createElement("option");e.value=v;e.textContent=v;sel.appendChild(e);});}
// populate
const evKeys=Object.keys(DATA);
opts($("fEvent"),evKeys.map(k=>DATA[k].label),"all events");
$("fEvent").options[0].value="";evKeys.forEach((k,i)=>{$("fEvent").options[i+1].value=k;});
const allRoles=new Set(),allGroups=new Set(),allEpi=new Set();
evKeys.forEach(k=>DATA[k].records.forEach(r=>{allGroups.add(r.grp);if(r.epi)allEpi.add(r.epi);r.me.forEach(m=>m.r&&allRoles.add(m.r));}));
opts($("fGroup"),[...allGroups].sort(),"all groups");
opts($("fRole"),[...allRoles].sort(),"all roles");
opts($("fEpi"),[...allEpi].sort(),"all epistemic");
function render(){
  const ev=$("fEvent").value,grp=$("fGroup").value,ent=$("fEntity").value.trim().toLowerCase(),role=$("fRole").value,epi=$("fEpi").value;
  let recs=[];evKeys.forEach(k=>{if(ev&&k!=ev)return;DATA[k].records.forEach(r=>recs.push([k,r]));});
  recs=recs.filter(([k,r])=>{
    if(grp&&r.grp!=grp)return false;
    if(epi&&r.epi!=epi)return false;
    if(ent||role){const ok=r.me.some(m=>(!ent||(m.e||"").toLowerCase().includes(ent))&&(!role||m.r==role));if(!ok)return false;}
    return true;});
  const cap=80;const out=$("out");
  $("count").textContent=recs.length+" record"+(recs.length==1?"":"s")+(recs.length>cap?" (showing "+cap+")":"");
  if(!recs.length){out.innerHTML='<div class="empty">No records match these filters.</div>';return;}
  out.innerHTML=recs.slice(0,cap).map(([k,r])=>card(k,r,ent,role)).join("");
}
function card(k,r,ent,role){
  const me=r.me.map(m=>{
    const hit=(ent&&(m.e||"").toLowerCase().includes(ent))||(role&&m.r==role)?
      ((!ent||(m.e||"").toLowerCase().includes(ent))&&(!role||m.r==role)?"hit":""):"";
    const pc=m.p>0?"pos":m.p<0?"neg":"zero";
    return `<tr class="${hit}"><td>${esc(m.e)}</td><td class="role ${rcat(m.r)}">${esc(m.r)}</td>`+
      `<td class="pol ${pc}">${m.p>0?"+":""}${esc(m.p)}</td><td>${esc(m.i)}</td><td class="ev">${esc(m.ev)}</td></tr>`;}).join("");
  const al=r.al.map(a=>`<span class="chip ${a.v=="positive"?"pos":a.v=="negative"?"neg":""}" title="${esc(a.a)} — ${esc(a.v)}">${esc(a.t)}</span>`).join("");
  const emp=r.emp.map(e=>`<span class="chip">${esc(e)}</span>`).join("");
  const sem=r.sem.map(s=>`<span class="sem">${esc(s)}</span>`).join("");
  const ents=r.ent.map(e=>`<span class="chip" title="${esc(e.t)}">${esc(e.m)} → ${esc(e.c)}</span>`).join("");
  const ca=r.ca||{};
  return `<div class="rec">
    <div class="rhead"><span class="src">${esc(r.src)}</span><span class="tag grp">${esc(r.grp)}</span>
      <span>${esc(r.date)}</span><span class="tag epi">${esc(r.epi)}</span>${r.on===false?'<span class="tag off">off-event</span>':''}
      <span>id ${esc(r.id)}</span><span>rerank ${esc((+r.rr).toFixed?(+r.rr).toFixed(2):r.rr)}</span></div>
    <div class="txt"><span class="lbl">text_used — exactly what gpt-5.5 read</span>${esc(r.text)||'<i>(empty)</i>'}</div>
    <div class="grid">
      <div class="cols2">
        <div class="fld"><div class="k">problem_definition (Entman 1)</div><div class="v">${esc(r.pd)||'—'}<br><span class="ev">${esc(r.pde)}</span></div></div>
        <div class="fld"><div class="k">causal_attribution (Entman 2)</div><div class="v">${esc(ca.cause_entity)||'—'}${ca.mechanism?' · '+esc(ca.mechanism):''}<br><span class="ev">${esc(ca.evidence)}</span></div></div>
      </div>
      <div class="fld"><div class="k">moral_evaluation (Entman 3) — role × stance per actor</div>
        <table class="me"><thead><tr><th>entity</th><th>role</th><th>polarity</th><th>intensity</th><th>evidence</th></tr></thead><tbody>${me||'<tr><td colspan=5>—</td></tr>'}</tbody></table></div>
      <div class="cols2">
        <div class="fld"><div class="k">treatment (Entman 4)</div><div class="v">${esc(r.tr)||'<span class="ev">no remedy prescribed</span>'}</div></div>
        <div class="fld"><div class="k">epistemic_status</div><div class="v">${esc(r.epi)}</div></div>
      </div>
      <div class="fld"><div class="k">action_labels — loaded terms (verbatim) + valence</div><div class="chips">${al||'—'}</div></div>
      <div class="fld"><div class="k">emphasized · semetko frames</div><div class="chips">${emp}</div><div style="margin-top:.3rem">${sem||'—'}</div></div>
      <div class="fld"><div class="k">entities — mention → canonical (${r.ent.length})</div><div class="chips">${ents||'—'}</div></div>
    </div></div>`;
}
["fEvent","fGroup","fRole","fEpi"].forEach(id=>$(id).addEventListener("change",render));
$("fEntity").addEventListener("input",render);
render();
</script>
""".replace("__PAYLOAD__",payload)
OUT.write_text(HTML,encoding="utf-8")
print("wrote",OUT,f"{len(HTML)/1024/1024:.2f} MB")
