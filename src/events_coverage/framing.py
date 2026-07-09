"""Per-message framing extraction (Entman functions + Semetko & Valkenburg generic frames).

The analytical unit is NOT a fact (facts are shared across already-matched coverage) but the
*interpretation* of those facts: which role each entity is cast in, how an action is labelled,
who is blamed, and whether the core claim is asserted or merely attributed. We extract this as a
structured record so stance/tone survives as typed fields instead of being flattened by a summary.

Vocabularies (Semetko frames, role inventory, epistemic enum) live in
`configs/framing_schema.yaml` and are loaded here so the instrument is editable without code edits.

LLM: OpenAI `gpt-5.5` via Structured Outputs (strict json_schema, backed by Pydantic).
"""

from __future__ import annotations

import enum
import json
import os
import time
from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel

from .paths import PROJECT_ROOT

FRAMING_SCHEMA_YAML = PROJECT_ROOT / "configs" / "framing_schema.yaml"

MODEL = os.environ.get("FRAMING_MODEL", "gpt-5.5")
REASONING_EFFORT = os.environ.get("FRAMING_REASONING_EFFORT", "low")
MAX_OUTPUT_TOKENS = int(os.environ.get("FRAMING_MAX_OUTPUT_TOKENS", "2048"))
MAX_TEXT_CHARS = int(os.environ.get("FRAMING_MAX_TEXT_CHARS", "2000"))


# --------------------------------------------------------------------- instrument (yaml)
@lru_cache(maxsize=1)
def load_instrument(path=FRAMING_SCHEMA_YAML) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _roles() -> list[str]:
    roles = list(load_instrument().get("roles", []))
    if "other" not in roles:
        roles.append("other")
    return roles


def _epistemic() -> list[str]:
    return list(load_instrument().get("epistemic_status", []))


# ------------------------------------------------------------------- pydantic schema
# Enums are built from the yaml so the strict schema enforces exactly the reviewed vocabulary.
RoleEnum = enum.Enum("RoleEnum", {r: r for r in _roles()}, type=str)
EpistemicEnum = enum.Enum("EpistemicEnum", {e: e for e in _epistemic()}, type=str)


class Entity(BaseModel):
    mention: str          # verbatim surface form from the text (Russian)
    canonical: str        # normalized cross-message name (English), e.g. "Russian forces"
    type: str             # military | state | person | place | org | group | other


class Action(BaseModel):
    predicate: str        # group-neutral verb, English, e.g. "took control of"
    agent: str            # canonical entity name
    target: str           # canonical entity / place name


class ActionLabel(BaseModel):
    action: str                                      # which action, short English
    term: str                                        # EXACT word the outlet uses (Russian)
    valence: Literal["positive", "negative", "neutral"]  # outlet's loading of the term
    evidence: str                                    # verbatim quote (Russian)


class MoralEval(BaseModel):
    entity: str           # canonical entity name
    role: RoleEnum        # how THIS text casts the entity (may contradict other outlets)
    polarity: int         # -2..2 stance toward the entity
    intensity: int        # 0..2 strength of that stance
    evidence: str         # verbatim quote (Russian)


class CausalAttribution(BaseModel):
    cause_entity: str | None     # who/what the text presents as the cause/initiator
    mechanism: str | None        # short English gloss of the causal story
    evidence: str | None         # verbatim quote (Russian) or null


class SemetkoFrames(BaseModel):
    conflict: bool
    human_interest: bool
    economic_consequences: bool
    morality: bool
    responsibility: bool


class FramingAnalysis(BaseModel):
    """What the LLM fills. Message metadata (id/source/group/date/text) is merged in afterwards."""

    on_event: bool                       # is THIS text actually about the target event?
    on_event_evidence: str | None

    entities: list[Entity]               # shared substrate
    actions: list[Action]

    problem_definition: str              # what the event "is" in this text (short English)
    problem_definition_evidence: str
    action_labels: list[ActionLabel]
    causal_attribution: CausalAttribution
    moral_evaluation: list[MoralEval]
    treatment: str | None                # prescribed action (short English) or null
    epistemic_status: EpistemicEnum
    epistemic_evidence: str
    emphasized: list[str]                # what is foregrounded (short English phrases)

    semetko: SemetkoFrames
    semetko_evidence: str                # brief justification / quote for the strongest frame


# --------------------------------------------------------------------------- prompts
def build_system_prompt() -> str:
    instr = load_instrument()
    sem = instr.get("semetko_frames", {})
    sem_lines = "\n".join(
        f"  - {name}: {d.get('desc','')}" for name, d in sem.items()
    )
    roles = ", ".join(_roles())
    epis = instr.get("epistemic_status", [])
    epis_lines = "\n".join(f"  - {e}" for e in epis)
    return f"""You are a media-framing analyst. You read ONE Russian-language news message about a \
specific event and extract HOW it frames that event — not whether the facts are true.

The texts have already been matched to the same event, so the underlying facts (who, what, where) \
are largely shared. The signal we want is the INTERPRETATION laid on top of those facts: which role \
each actor is cast in, how an action is named, who is blamed, and whether claims are asserted or \
merely attributed to a source. Two outlets can describe the same action as «освобождение» or as \
«оккупация»/«теракт» — capture that difference precisely.

Rules:
- Separate the SHARED SUBSTRATE (entities, actions — keep these group-neutral) from the FRAMING.
- Every interpretive field must include a VERBATIM quote from the text as its `evidence` (copy the \
Russian exactly; do not paraphrase). If there is no textual basis for a field, leave it null/empty — \
never invent.
- `moral_evaluation.role`: choose how THIS text casts the entity, even if it contradicts reality or \
other outlets. Allowed roles: {roles}.
- `action_labels`: up to 5 MOST SALIENT framing terms. `term` is the EXACT Russian word/phrase \
the outlet uses for the action; `valence` is positive/negative/neutral as the outlet loads that \
term toward its own preferred side (e.g. «освобождение»=positive, «оккупация»/«теракт»=negative).
- `epistemic_status`: how the message presents its core claim:
{epis_lines}
- `entities[].canonical`: a stable ENGLISH name so the same actor merges across messages \
(e.g. ВС РФ / российские войска / наши бойцы -> "Russian forces"; ВСУ / украинские войска -> \
"Ukrainian forces"; Суджа -> "Sudzha").
- Semetko & Valkenburg generic frames (mark present only if the TEXT actually does that framing):
{sem_lines}
- `on_event`: true only if the message is substantively about the target event (guards against \
digests that bundle unrelated items).
- Analytical free-text fields (problem_definition, action, mechanism, emphasized, predicate) in \
concise English; `term`, `mention`, and all `evidence` quotes stay verbatim Russian.

Be precise and literal. Do not editorialize."""


def build_user_prompt(text: str, event_name: str, event_desc: str = "") -> str:
    ctx = f"Target event: «{event_name}»"
    if event_desc:
        ctx += f"\nEvent context: {event_desc}"
    return f"{ctx}\n\n--- MESSAGE ---\n{text}\n--- END MESSAGE ---"


# ----------------------------------------------------------------- text normalization
def normalize_text(original_message: str | None, summary: str | None = None,
                   max_chars: int = MAX_TEXT_CHARS) -> str:
    """Unwrap Telegram JSON blobs (war/military channels), fall back to summary, truncate.

    War/military sources store original_message as a serialized Telegram object:
    `{"_": "Message", ..., "message": "<real text>"}`. Pull the `message` field out.
    """
    text = (original_message or "").strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and obj.get("message"):
                text = str(obj["message"]).strip()
        except (ValueError, TypeError):
            pass
    if not text:
        text = (summary or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …"
    return text


# --------------------------------------------------------------------------- OpenAI
def get_openai_client(api_key: str | None = None):
    """Build an OpenAI client, loading OPENAI_API_KEY from .env if needed."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your OpenAI key "
            "(framing extraction uses model gpt-5.5 via Structured Outputs)."
        )
    from openai import OpenAI

    return OpenAI(api_key=key, max_retries=5, timeout=90)


def _is_rate_limit(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return "ratelimit" in name or code == 429


def structured_parse(client, system_prompt: str, user_prompt: str, text_format,
                     model: str = MODEL, max_output_tokens: int = MAX_OUTPUT_TOKENS,
                     reasoning_effort: str = REASONING_EFFORT):
    """OpenAI Structured Outputs -> (parsed_obj, usage_dict). Reusable for any Pydantic schema.

    Responses API first (gpt-5.x's primary surface), Chat Completions fallback. Robust to:
    an unsupported reasoning param, and runs where reasoning consumes the whole token budget so
    the parsed object is None — both retry with the non-reasoning / chat variant.
    """
    base = dict(model=model, instructions=system_prompt, input=user_prompt,
                text_format=text_format, max_output_tokens=max_output_tokens)
    for kwargs in ({**base, "reasoning": {"effort": reasoning_effort}}, base):
        try:
            resp = client.responses.parse(**kwargs)
        except TypeError:
            continue  # reasoning param not supported -> retry without it
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc):
                raise
            break  # fall through to chat completions
        if resp.output_parsed is not None:
            u = resp.usage
            return resp.output_parsed, {
                "in": getattr(u, "input_tokens", 0), "out": getattr(u, "output_tokens", 0)}
        # else: length/refusal consumed the budget -> try the next variant

    msgs = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]
    chat_base = dict(model=model, messages=msgs, response_format=text_format,
                     max_completion_tokens=max_output_tokens)
    for kwargs in ({**chat_base, "reasoning_effort": reasoning_effort}, chat_base):
        try:
            resp = client.chat.completions.parse(**kwargs)
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001 - e.g. LengthFinishReasonError -> try next variant
            if _is_rate_limit(exc):
                raise
            continue
        msg = resp.choices[0].message
        if msg.parsed is not None:
            u = resp.usage
            return msg.parsed, {
                "in": getattr(u, "prompt_tokens", 0), "out": getattr(u, "completion_tokens", 0)}
    raise RuntimeError("structured parse failed (length/refusal/schema) on both APIs")


def extract_framing(client, text: str, event_name: str, event_desc: str = "",
                    model: str = MODEL, max_retries: int = 5):
    """Extract one FramingAnalysis from a normalized message text. Returns (analysis, usage)."""
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(text, event_name, event_desc)
    for attempt in range(max_retries + 1):
        try:
            return structured_parse(client, system_prompt, user_prompt, FramingAnalysis, model)
        except Exception as exc:  # noqa: BLE001 - retry only on rate limits
            if _is_rate_limit(exc) and attempt < max_retries:
                wait = min(60.0, 2.0**attempt)
                print(f"    rate limited; retry {attempt + 1}/{max_retries} in {wait:.0f}s ...")
                time.sleep(wait)
                continue
            raise


# ------------------------------------------------------------- entity canonicalization
def canonicalize_entities(client, canonicals: list[str], model: str = MODEL) -> dict[str, str]:
    """Merge near-duplicate canonical entity names via one LLM call.

    Input: the unique `canonical` strings produced during extraction
    (e.g. "Russian forces", "Russian military", "Russian army").
    Output: {original -> merged canonical}. Reduces role-contingency fragmentation.
    """
    uniq = sorted({c for c in canonicals if c and c.strip()})
    if len(uniq) <= 1:
        return {c: c for c in uniq}

    class CanonItem(BaseModel):
        original: str
        merged: str

    class CanonResult(BaseModel):
        items: list[CanonItem]

    listing = "\n".join(f"- {c}" for c in uniq)
    sys = ("You merge entity names that refer to the SAME real-world actor into one canonical "
           "English label. Keep genuinely different actors separate. Return every input name "
           "mapped to its merged label (identity map if it is already canonical).")
    usr = f"Entity names:\n{listing}"
    try:
        result, _ = structured_parse(client, sys, usr, CanonResult, model, max_output_tokens=8000)
        items = result.items
    except Exception:  # noqa: BLE001 - fall back to identity on any failure
        return {c: c for c in uniq}
    mapping = {it.original: it.merged for it in items if it.original in set(uniq)}
    for c in uniq:  # ensure totality
        mapping.setdefault(c, c)
    return mapping
