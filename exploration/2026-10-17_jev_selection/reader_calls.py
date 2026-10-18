#!/usr/bin/env python
"""Paid step: cheap API models read the cut-off sample (prompts from reader_prompts.py).

Each model answers every prompt in reader_labelling/prompts/ through OpenRouter chat completions
with the same yes/no JSON schema Codex used. Resumable; each model's spend is added to
spend.jsonl, and the step refuses to start past calls.CAP_USD.

  reader_calls.py run [model ...]     answer the prompts
  reader_calls.py collect             answers -> reader_labels/<model>/<slug>.json {labels}
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import calls as K
import common as C
from events_coverage import matching as M

DIR = C.OUT / "reader_labelling"
URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = {
    "deepseek-v4-flash": {"model": "deepseek/deepseek-v4-flash"},
    # openai/gpt-6-luna was the planned second reader; OpenRouter refuses every OpenAI model for
    # this account (403 "violation of provider Terms Of Service", even on "Say ok").
    # with reasoning on (default or effort low) it thought 20-24k tokens per slice, ~$0.01 each
    "qwen3.8-flash": {"model": "qwen/qwen3.8-flash", "reasoning": {"enabled": False}},
}


def ask(key, cfg, text):
    schema = json.loads((C.R.OUT / "labels" / "schema.json").read_text())
    body = {"model": cfg["model"], "temperature": 0, "usage": {"include": True},
            "messages": [{"role": "user", "content": text}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "labels", "strict": True, "schema": schema}}}
    if "reasoning" in cfg:
        body["reasoning"] = cfg["reasoning"]
    err, paid = "", {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
    want = {int(x) for x in re.findall(r"\[id (\d+)\]", text)}
    for attempt in range(5):
        try:
            r = requests.post(URL, timeout=300, json=body, headers={"Authorization": f"Bearer {key}"})
            if r.ok:
                d = r.json()
                for k in paid:                       # a reply we cannot use is still billed
                    paid[k] += d.get("usage", {}).get(k, 0) or 0
                ans = json.loads(d["choices"][0]["message"]["content"])
                got = {int(x["id"]) for x in ans["labels"] if str(x["id"]).strip().isdigit()}
                if want <= got:
                    return ans, {**paid, "usage": d.get("usage", {})}
                err = f"answer covers {len(want & got)} of {len(want)} ids"
            else:
                err = f"{r.status_code} {r.text[:300]}"
        except (requests.RequestException, KeyError, TypeError, ValueError) as ex:
            err = repr(ex)[:300]
        time.sleep(4 * (attempt + 1))
    return None, {**paid, "error": err}


def run(names):
    key = M.get_openrouter_key()
    for name in names:
        cfg = MODELS[name]
        K.guard()
        out = DIR / "out" / name
        out.mkdir(parents=True, exist_ok=True)
        todo = [p for p in sorted((DIR / "prompts").glob("*.txt")) if not (out / f"{p.stem}.json").exists()]
        todo = todo[:int(os.environ.get("LIMIT", 10**6))]  # LIMIT=1 for a smoke test
        done = []

        def one(p):
            ans, paid = ask(key, cfg, p.read_text(encoding="utf-8"))
            done.append(paid)
            if ans is None:
                print(f"{name} {p.stem} FAILED {paid['error']}", flush=True)
            else:
                (out / f"{p.stem}.json").write_text(json.dumps({**ans, "usage": paid["usage"]}, ensure_ascii=False))

        try:
            with ThreadPoolExecutor(8) as pool:
                list(pool.map(one, todo))
        finally:
            cost = sum(d["cost"] for d in done)
            tin, tout = sum(d["prompt_tokens"] for d in done), sum(d["completion_tokens"] for d in done)
            K.book("reader", cost, model=cfg["model"], prompts=len(done), input_tokens=tin, output_tokens=tout)
            print(f"{name}: {len(done)} of {len(todo)} prompts, {tin:,} in / {tout:,} out tokens, ${cost:.4f}; "
                  f"ledger ${K.spent():.3f}", flush=True)


def collect():
    from reader_prompts import pools
    _, by_event = pools()
    for name, cfg in MODELS.items():
        target = C.OUT / "reader_labels" / name
        target.mkdir(parents=True, exist_ok=True)
        for slug, ids in by_event.items():
            labels, usage = {}, {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0}
            for p in sorted((DIR / "out" / name).glob(f"{slug}_[0-9][0-9][0-9].json")):
                d = json.loads(p.read_text())
                for k in usage:
                    usage[k] += d["usage"].get(k, 0) or 0
                for item in d["labels"]:
                    labels[int(str(item["id"]).strip())] = item["label"] == "yes"
            missing = [i for i in ids if i not in labels]
            (target / f"{slug}.json").write_text(json.dumps({
                "slug": slug, "reader": cfg["model"], "prompt": "run.PROMPT, slices of 50",
                "date": time.strftime("%Y-%m-%d"), "usage": usage, "missing": missing,
                "labels": {str(i): labels[i] for i in ids if i in labels}}))
            print(f"{name} {slug}: {len(ids) - len(missing)} of {len(ids)} labelled, ${usage['cost']:.4f}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2:] or list(MODELS))
    else:
        collect()
