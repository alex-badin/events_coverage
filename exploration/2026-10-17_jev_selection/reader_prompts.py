#!/usr/bin/env python
"""Free step: prompts for an API model to read the cut-off sample instead of Codex.

The sample-cut rule in evaluate.py draws 100 posts per event from the labelled posts (dev: the
~800 Codex-labelled posts; hold-out: the 750 stratified ones). To re-run its 200 draws with a
different reader, that reader labels every post a draw can pick, i.e. the same posts Codex
labelled, with the same prompt (run.PROMPT: event name, respondents' wordings, window; no brief)
in slices of 50. Prompts go to data/interim/jev_selection/reader_labelling/prompts/.
"""
import json

import numpy as np

import common as C
import evaluate as V

DIR = C.OUT / "reader_labelling"


def pools():
    posts, labels = C.R.load_posts(), C.R.load_labels()
    out = {s: V.dev_data(s, posts, labels)[0] for s in C.DEV}
    out.update({s: V.holdout_data(s)[0] for s in C.HOLDOUT})
    return posts, out


if __name__ == "__main__":
    posts, by_event = pools()
    (DIR / "prompts").mkdir(parents=True, exist_ok=True)
    chars = 0
    for slug, ids in by_event.items():
        e = C.event(slug)
        ids = [int(i) for i in np.random.default_rng(5).permutation(ids)]
        for k in range(0, len(ids), C.R.SLICE):
            block = "\n\n".join(f"[id {i}] {posts[i]['text'][:C.POST_CHARS]}" for i in ids[k:k + C.R.SLICE])
            text = C.R.PROMPT.format(week=e["week"], name=e["name"], quotes="; ".join(e["quotes"]),
                                     lo=e["window"][0], hi=e["window"][1], posts=block)
            (DIR / "prompts" / f"{slug}_{k // C.R.SLICE:03d}.txt").write_text(text, encoding="utf-8")
            chars += len(text)
        print(f"{slug}: {len(ids)} posts")
    n = len(list((DIR / "prompts").glob("*.txt")))
    print(f"{sum(map(len, by_event.values()))} posts in {n} prompts, {chars:,} characters")
