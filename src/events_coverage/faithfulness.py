"""Faithfulness checks for framing records (lean, Russian-appropriate).

MiniCheck/AlignScore are English-trained, so instead we score faithfulness two ways:

1. Evidence-span PROVENANCE (free, programmatic): every interpretive field must quote the source
   verbatim; we fuzzy-match each quote back into `text_used` and flag fabricated quotes.
2. LLM-JUDGE grounding (sampled): does `text_used` actually support the assigned roles / epistemic
   status / action labels? Run on a stratified sample, not every record.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from pydantic import BaseModel


# ---------------------------------------------------------------- evidence provenance
def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)  # drop punctuation incl « » — …
    return re.sub(r"\s+", " ", s).strip()


def _is_grounded(text_norm: str, span: str, threshold: float = 0.85) -> bool:
    span_norm = _norm(span)
    if len(span_norm) < 6:          # too short to judge; don't count as fabricated
        return True
    if span_norm in text_norm:
        return True
    sm = SequenceMatcher(None, text_norm, span_norm, autojunk=False)
    m = sm.find_longest_match(0, len(text_norm), 0, len(span_norm))
    return (m.size / len(span_norm)) >= threshold


def collect_evidence(record: dict) -> list[tuple[str, str]]:
    """Return [(field_path, span)] for every non-empty evidence quote in a record."""
    spans: list[tuple[str, str]] = []

    def add(path, val):
        if val and str(val).strip():
            spans.append((path, str(val)))

    # NB: semetko_evidence is a rationale (often diffuse), not a single verbatim span, so it is
    # deliberately NOT provenance-scored here.
    add("on_event_evidence", record.get("on_event_evidence"))
    add("problem_definition_evidence", record.get("problem_definition_evidence"))
    add("epistemic_evidence", record.get("epistemic_evidence"))
    for i, a in enumerate(record.get("action_labels") or []):
        add(f"action_labels[{i}].evidence", a.get("evidence"))
    for i, m in enumerate(record.get("moral_evaluation") or []):
        add(f"moral_evaluation[{i}].evidence", m.get("evidence"))
    ca = record.get("causal_attribution") or {}
    add("causal_attribution.evidence", ca.get("evidence"))
    return spans


def provenance_score(record: dict, threshold: float = 0.85) -> dict:
    """Fraction of evidence quotes that actually occur (fuzzily) in text_used."""
    text_norm = _norm(record.get("text_used"))
    spans = collect_evidence(record)
    if not spans:
        return {"score": None, "n_total": 0, "n_found": 0, "missing": []}
    missing = [(p, s) for p, s in spans if not _is_grounded(text_norm, s, threshold)]
    n_found = len(spans) - len(missing)
    return {"score": n_found / len(spans), "n_total": len(spans), "n_found": n_found,
            "missing": [{"field": p, "span": s} for p, s in missing]}


def provenance_summary(records: list[dict], threshold: float = 0.85) -> dict:
    """Aggregate provenance across a set of records."""
    scored = [provenance_score(r, threshold) for r in records]
    have = [s for s in scored if s["score"] is not None]
    if not have:
        return {"n_records": len(records), "mean_score": None}
    mean = sum(s["score"] for s in have) / len(have)
    perfect = sum(1 for s in have if s["score"] == 1.0)
    flagged = [(r.get("message_id"), s) for r, s in zip(records, scored)
               if s["score"] is not None and s["score"] < 1.0]
    return {"n_records": len(records), "n_with_evidence": len(have), "mean_score": mean,
            "pct_fully_grounded": perfect / len(have),
            "flagged": flagged}


# ------------------------------------------------------------------------ LLM judge
class GroundingVerdict(BaseModel):
    supported: bool          # are the framing labels supported by the text?
    confidence: float        # 0..1
    problems: list[str]      # short notes on any unsupported label


def judge_record(client, record: dict, model: str) -> GroundingVerdict:
    """Ask the model whether the assigned roles/epistemic/labels are supported by text_used."""
    roles = "; ".join(f"{m.get('entity')}={m.get('role')}" for m in record.get("moral_evaluation") or [])
    labels = "; ".join(f"{a.get('action')}='{a.get('term')}'" for a in record.get("action_labels") or [])
    summary = (
        f"epistemic_status={record.get('epistemic_status')}\n"
        f"problem_definition={record.get('problem_definition')}\n"
        f"entity_roles={roles}\naction_labels={labels}\n"
        f"causal_cause={(record.get('causal_attribution') or {}).get('cause_entity')}"
    )
    sys = ("You verify a media-framing annotation against its Russian source text. Decide whether "
           "the assigned entity roles, epistemic status and action labels are genuinely supported "
           "by the text (not invented, not contradicted). List any unsupported label briefly.")
    usr = f"--- TEXT ---\n{record.get('text_used')}\n--- ANNOTATION ---\n{summary}"
    try:
        resp = client.responses.parse(model=model, instructions=sys, input=usr,
                                       text_format=GroundingVerdict, max_output_tokens=600)
        return resp.output_parsed
    except Exception:  # noqa: BLE001
        resp = client.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            response_format=GroundingVerdict, max_completion_tokens=600)
        return resp.choices[0].message.parsed
