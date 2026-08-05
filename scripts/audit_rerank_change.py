#!/usr/bin/env python3
"""Compare two builds of the same events and draw a sample to read by hand.

The relevance step changed on 2026-08-03 from one glued query (event name + all respondent
quotes in a single string) to one query per probe with each post's best score kept. That
change can only be judged by reading posts, so this script does not judge anything: it lines
the two builds up and prints the disagreements in a form a person can mark.

Two disagreement directions, printed separately because they mean different things:
  ADDED   — kept by the new build, not by the old one. Are these real coverage that the old
            method missed, or noise let in by giving each post several chances?
  DROPPED — kept by the old build, not by the new one. Should be rare; if it is not, the
            change is trading one kind of miss for another.

Usage:
    python scripts/audit_rerank_change.py                     # counts + sample of ADDED
    python scripts/audit_rerank_change.py --direction dropped # the other direction
    python scripts/audit_rerank_change.py --event kursk_2025w11 --sample 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

PROCESSED = PROJECT_ROOT / "data" / "processed"

# (short name, old build slug, new build slug)
PAIRS = [
    ("dc_aircrash_2025w05", "event_dc_aircrash_2025w05_qwen3",
     "event_dc_aircrash_2025w05_qwen3_perphrase"),
    ("kursk_2025w11", "event_kursk_2025w11_qwen3",
     "event_kursk_2025w11_qwen3_perphrase"),
    ("prices_2025w11", "event_prices_2025w11_qwen3",
     "event_prices_2025w11_qwen3_perphrase"),
    ("putin_trump_call_2025w08", "event_putin_trump_call_2025w08_qwen3",
     "event_putin_trump_call_2025w08_qwen3_perphrase"),
    ("trump_zelensky_2025w10", "event_trump_zelensky_2025w10_qwen3",
     "event_trump_zelensky_2025w10_qwen3_perphrase"),
    ("us_russia_contacts_2025w09", "event_us_russia_contacts_2025w09_qwen3",
     "event_us_russia_contacts_2025w09_qwen3_perphrase"),
]

KEY = ["source", "message_id"]


def load_kept(slug: str) -> pd.DataFrame:
    path = PROCESSED / f"{slug}_dataset.csv"
    if not path.exists():
        raise SystemExit(f"missing {path}")
    df = pd.read_csv(path)
    df["message_id"] = df["message_id"].astype(str)
    return df


def load_candidates(slug: str) -> pd.DataFrame:
    path = PROCESSED / f"{slug}_candidates.csv"
    if not path.exists():
        raise SystemExit(f"missing {path}")
    df = pd.read_csv(path)
    df["message_id"] = df["message_id"].astype(str)
    return df


def compare(old_slug: str, new_slug: str):
    old_kept, new_kept = load_kept(old_slug), load_kept(new_slug)
    old_keys = set(map(tuple, old_kept[KEY].values))
    new_keys = set(map(tuple, new_kept[KEY].values))

    # np.array, not a plain list: pandas reads an EMPTY list as "select these columns",
    # which silently returns a frame with no columns when one side kept nothing.
    def mask(df: pd.DataFrame, seen: set) -> np.ndarray:
        return np.array([tuple(k) not in seen for k in df[KEY].values], dtype=bool)

    added = new_kept[mask(new_kept, old_keys)]
    dropped = old_kept[mask(old_kept, new_keys)]

    # What the new run scored the dropped posts, so a reader can see how close they were.
    new_cand = load_candidates(new_slug)[[*KEY, "rerank_score"]].rename(
        columns={"rerank_score": "new_score"}
    )
    dropped = dropped.merge(new_cand, on=KEY, how="left")
    return old_kept, new_kept, added, dropped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", default=None, help="short name from PAIRS; default all")
    ap.add_argument("--direction", choices=["added", "dropped", "none"], default="added")
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260803)
    ap.add_argument("--chars", type=int, default=200, help="how much of each post to print")
    args = ap.parse_args()

    pairs = [p for p in PAIRS if args.event in (None, p[0])]
    if not pairs:
        raise SystemExit(f"no event matches {args.event!r}")

    summary = []
    for short, old_slug, new_slug in pairs:
        old_kept, new_kept, added, dropped = compare(old_slug, new_slug)
        summary.append({
            "event": short,
            "kept_old": len(old_kept),
            "kept_new": len(new_kept),
            "added": len(added),
            "dropped": len(dropped),
            "dropped_share_of_old": (
                round(len(dropped) / len(old_kept), 4) if len(old_kept) else None
            ),
        })

        if args.direction == "none":
            continue
        rows = added if args.direction == "added" else dropped
        if rows.empty:
            print(f"\n{'=' * 78}\n{short}: nothing in the {args.direction} direction\n")
            continue
        take = rows.sample(min(args.sample, len(rows)), random_state=args.seed)
        take = take.sort_values("rerank_score", ascending=False)
        print(f"\n{'=' * 78}")
        print(f"{short}  —  {args.direction.upper()}: {len(rows):,} posts, showing {len(take)}")
        print(f"{'=' * 78}")
        for n, (_, r) in enumerate(take.iterrows(), 1):
            extra = ""
            if args.direction == "dropped":
                new_score = r.get("new_score")
                extra = (
                    f" new_score={new_score:.4f}" if pd.notna(new_score) else " new_score=absent"
                )
            probe = r.get("rerank_probe", "")
            probe_txt = f" probe='{str(probe)[:45]}'" if isinstance(probe, str) else ""
            print(f"\n[{n:>2}] {r['source']}/{r['message_id']}  {str(r['date'])[:10]}  "
                  f"score={r['rerank_score']:.4f}{extra}{probe_txt}")
            text = r["summary"] if isinstance(r["summary"], str) else r["original_message"]
            print("     " + str(text)[: args.chars].replace("\n", " "))

    print(f"\n{'=' * 78}")
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
