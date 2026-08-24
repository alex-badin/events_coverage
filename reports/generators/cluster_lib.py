"""Clustering helpers for framing-field values."""
import numpy as np, re, collections
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SP=ROOT/"data"/"interim"/"framing_embeddings"

STOP=set("the a an of to in and is are as be by for on with at from that this it its into after over than then so they them their he his her we you your i not no will would can may has have had been being other another more most very also which who whom whose what when where while about between during against within without toward towards amid due both either neither each any all some such only just but or if because presented framing framed event message text reported claims attributed emphasizes emphasizing emphasized side sides".split())

def load(slug, field):
    d=np.load(SP/f"emb_{slug}_{field}.npz", allow_pickle=True)
    return d["vecs"].astype(np.float32), d["texts"], d["groups"], d["sources"], d["causes"], d["ids"]

def l2(v): return v/ (np.linalg.norm(v,axis=1,keepdims=True)+1e-9)

def pick_k_kmeans(X, lo=3, hi=14):
    best=None
    for k in range(lo,hi+1):
        km=KMeans(n_clusters=k,n_init=10,random_state=0).fit(X)
        s=silhouette_score(X,km.labels_,metric="cosine")
        if best is None or s>best[1]: best=(k,s,km.labels_)
    return best  # (k, sil, labels)

def agglo(X, thresh):
    return AgglomerativeClustering(metric="cosine",linkage="average",
                                   distance_threshold=thresh,n_clusters=None).fit_predict(X)

def medoid_idx(X, idxs):
    sub=X[idxs]; c=sub.mean(0); c/=(np.linalg.norm(c)+1e-9)
    sims=sub@c
    return idxs[int(np.argmax(sims))]

def top_terms(texts, k=6):
    cnt=collections.Counter()
    for t in texts:
        for w in re.findall(r"[A-Za-z]{3,}", t.lower()):
            if w not in STOP: cnt[w]+=1
    return [w for w,_ in cnt.most_common(k)]

def summarize(labels, X, texts, min_size=1):
    order=collections.Counter(labels).most_common()
    rows=[]
    for lab,n in order:
        idxs=np.where(labels==lab)[0]
        med=medoid_idx(X, idxs)
        rows.append(dict(label=lab,size=n,medoid=str(texts[med]),
                         terms=top_terms([str(texts[i]) for i in idxs])))
    return rows
