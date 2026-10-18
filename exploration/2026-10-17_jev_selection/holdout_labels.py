#!/usr/bin/env python
"""Free step: the reference labels for the hold-out events.

Sample: the 3,000 candidates by full-text cosine, cut into rank bands; 150 posts drawn at
random from each band, independent of Jev and Cohere. Each labelled post stands for
band size / 150 candidates. Codex labels them with the same prompt as the dev events
(run.PROMPT: event name, respondents' wordings, window; no brief), via codex_answer.sh.

  prompts   write the slices of 50 posts
  collect   answers -> holdout_labels/<slug>.json {labels, weights}
"""
import json
import sys

import numpy as np

import common as C

BANDS = [(0, 150), (150, 500), (500, 1000), (1000, 2000), (2000, 3000)]
PER_BAND = 150
DIR = C.OUT / "holdout_labelling"


def sample(slug):
    ranked = C.ranked_candidates(slug)
    rng = np.random.default_rng(17)
    picked, weight = [], {}
    for lo, hi in BANDS:
        band = ranked[lo:hi]
        take = rng.choice(len(band), size=min(PER_BAND, len(band)), replace=False)
        for t in take:
            picked.append(band[t]); weight[band[t]] = len(band) / len(take)
    return picked, weight


def prompts():
    posts = C.R.load_posts()
    (DIR / "prompts").mkdir(parents=True, exist_ok=True)
    (DIR / "schema.json").write_text((C.R.OUT / "labels" / "schema.json").read_text())
    for slug in C.HOLDOUT:
        e = C.event(slug)
        ids, _ = sample(slug)
        ids = [int(i) for i in np.random.default_rng(5).permutation(ids)]
        for k in range(0, len(ids), C.R.SLICE):
            block = "\n\n".join(f"[id {i}] {posts[i]['text'][:C.POST_CHARS]}" for i in ids[k:k + C.R.SLICE])
            text = C.R.PROMPT.format(week=e["week"], name=e["name"], quotes="; ".join(e["quotes"]),
                                     lo=e["window"][0], hi=e["window"][1], posts=block)
            (DIR / "prompts" / f"{slug}_{k // C.R.SLICE:03d}.txt").write_text(text, encoding="utf-8")
        print(f"{slug}: {len(ids)} posts")


def collect():
    (C.OUT / "holdout_labels").mkdir(exist_ok=True)
    for slug in C.HOLDOUT:
        ids, weight = sample(slug)
        labels = {}
        for p in sorted((DIR / "out").glob(f"{slug}_*.json")):
            for item in json.loads(p.read_text())["labels"]:
                labels[int(item["id"])] = item["label"] == "yes"
        missing = [i for i in ids if i not in labels]
        if missing:
            raise SystemExit(f"{slug}: {len(missing)} posts unlabelled; rerun codex_answer.sh")
        (C.OUT / "holdout_labels" / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "labeller": "gpt-6.1-sol via codex exec, reasoning medium", "bands": BANDS,
            "labels": {str(i): labels[i] for i in ids}, "weights": {str(i): weight[i] for i in ids}}))
        on = sum(weight[i] for i in ids if labels[i])
        print(f"{slug}: {sum(labels[i] for i in ids)} of {len(ids)} labelled on-event; "
              f"estimated {on:.0f} of 3,000 candidates")


if __name__ == "__main__":
    {"prompts": prompts, "collect": collect}[sys.argv[1]]()
