#!/usr/bin/env python
"""Runs ON NEO (C:\\emb_test\\ec\\neo_qwen_retrieve.py) — never on the Mac.

Scores the Qwen3 sidecar window [start, end) against a small query matrix shipped
from the Mac. The 29GB sidecar and the O(window_size x n_probes) dot product both
stay on this machine; only the tiny query vectors (in) and per-doc scores (out)
cross the network. Invoked remotely by
events_coverage.matching.qwen_retrieve_remote() over SSH.

Args: start_date end_date query_npy_path out_tsv_path [sidecar_dir]
Output tsv columns: message_id, source, date, max_sim, best_probe_idx
"""
import sys

import numpy as np

SIDECAR_DEFAULT = "C:/emb_test/ec/data/processed/qwen3emb_8b"
DIM = 4096
ROW_BYTES = DIM * 2


def main():
    start_s, end_s, query_path, out_path = sys.argv[1:5]
    sidecar_dir = sys.argv[5] if len(sys.argv) > 5 else SIDECAR_DEFAULT

    matches = []  # (row_idx, message_id, source, date)
    with open(f"{sidecar_dir}/index.tsv", encoding="utf-8") as f:
        for i, line in enumerate(f):
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            mid, src, dt = parts
            if dt < start_s:
                continue
            if dt >= end_s:  # index is sorted ascending by date -> safe early exit
                break
            matches.append((i, mid, src, dt))

    if not matches:
        open(out_path, "w", encoding="utf-8").close()
        print("0 matches")
        return

    query = np.load(query_path).astype(np.float32)
    query /= np.linalg.norm(query, axis=1, keepdims=True)

    rows = []
    with open(f"{sidecar_dir}/vectors.f16", "rb") as vf:
        for i, *_ in matches:
            vf.seek(i * ROW_BYTES)
            rows.append(np.frombuffer(vf.read(ROW_BYTES), dtype=np.float16))
    doc = np.vstack(rows).astype(np.float32)
    doc /= np.maximum(np.linalg.norm(doc, axis=1, keepdims=True), 1e-12)

    sims = doc @ query.T
    max_sim = sims.max(axis=1)
    best_probe = sims.argmax(axis=1)

    with open(out_path, "w", encoding="utf-8") as g:
        for (_, mid, src, dt), sim, bp in zip(matches, max_sim, best_probe, strict=True):
            g.write(f"{mid}\t{src}\t{dt}\t{sim:.6f}\t{int(bp)}\n")
    print(f"{len(matches)} matches scored")


if __name__ == "__main__":
    main()
