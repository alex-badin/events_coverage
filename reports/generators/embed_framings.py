#!/usr/bin/env python3
"""Embed problem_definition and causal-claim (cause_entity + mechanism) per event, cache to .npy.
Cheap one-off so clustering experiments don't re-hit the API."""
import json, sys, hashlib
import numpy as np
from pathlib import Path
ROOT=Path("/Users/alexbadin/GitHub/_projects/events_coverage")
SP=Path("/Users/alexbadin/GitHub/_projects/events_coverage/data/interim/framing_embeddings")
sys.path.insert(0,str(ROOT))
from src.events_coverage.framing import get_openai_client
MODEL="text-embedding-3-large"

def load(slug):
    return [r for r in (json.loads(l) for l in open(ROOT/f"data/interim/event_{slug}_framing.jsonl",encoding="utf-8")) if r.get("on_event",True)]

def build_items(R, field):
    """Return list of dicts: {text, group, source, id, cause_entity} for the clustering target."""
    items=[]
    for r in R:
        g=r["media_group"]; src=r["source"]; mid=r.get("message_id")
        if field=="problem_definition":
            t=(r.get("problem_definition") or "").strip()
            if t: items.append(dict(text=t,group=g,source=src,id=mid,cause=None))
        elif field=="treatment":
            t=(r.get("treatment") or "").strip()
            if t: items.append(dict(text=t,group=g,source=src,id=mid,cause=None))
        else:  # causal: cause_entity + mechanism
            ca=r.get("causal_attribution") or {}
            ce=(ca.get("cause_entity") or "").strip(); me=(ca.get("mechanism") or "").strip()
            if not (ce or me): continue
            t=(f"{ce}: {me}" if ce and me else (ce or me)).strip()
            items.append(dict(text=t,group=g,source=src,id=mid,cause=ce or None))
    return items

def embed(texts):
    client=get_openai_client()
    out=[]
    B=512
    for i in range(0,len(texts),B):
        chunk=texts[i:i+B]
        resp=client.embeddings.create(model=MODEL,input=chunk)
        out.extend([d.embedding for d in resp.data])
        print(f"    embedded {min(i+B,len(texts))}/{len(texts)}")
    return np.asarray(out,dtype=np.float32)

EVENTS=[("kursk_2025w11"),("trump_zelensky_2025w10")]
FIELDS=["problem_definition","causal","treatment"]
for slug in EVENTS:
    R=load(slug)
    for field in FIELDS:
        items=build_items(R,field)
        texts=[it["text"] for it in items]
        cache=SP/f"emb_{slug}_{field}.npz"
        print(f"{slug} / {field}: {len(texts)} items -> {cache.name}")
        vecs=embed(texts)
        np.savez(cache, vecs=vecs,
                 texts=np.array(texts,dtype=object),
                 groups=np.array([it["group"] for it in items],dtype=object),
                 sources=np.array([it["source"] for it in items],dtype=object),
                 causes=np.array([it["cause"] for it in items],dtype=object),
                 ids=np.array([it["id"] for it in items],dtype=object))
print("done.")
