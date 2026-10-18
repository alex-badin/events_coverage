#!/usr/bin/env python
"""Free step: one prompt per event asking for a short brief of the event — what happened, what
counts as coverage, what does not. The model sees the FOM name and respondents' wordings and the
40 posts closest by full-text cosine (first 500 characters each). Answered by brief.sh (Codex).
In production this would be one cheap model call per event, like claim_prep in
misinfo_tracking_moldova.
"""
import json

import common as C

PROMPT = """Ниже — событие из еженедельного опроса ФОМ: так респонденты назвали то, что им запомнилось
за неделю, и самые близкие к нему по смыслу посты новостных Telegram-каналов за окно поиска.

Событие: «{name}» (неделя опроса {week})
Как его описывали респонденты: {quotes}
Окно поиска: {lo} — {hi}.

Напиши краткое описание события для модели, которая будет решать по каждому посту, сообщает ли
он об этом событии. Три поля, по-русски:
- what_happened: что произошло, когда, где, кто участники — 2–4 предложения с конкретными
  деталями, по которым пост можно узнать (имена, места, даты, числа);
- counts: что ещё считается освещением события: реакции на него, его прямые последствия,
  подготовка и продолжение, обсуждение — 2–4 пункта одной строкой;
- does_not_count: похожие темы и события, которые к нему не относятся (другие встречи,
  другие атаки, общие новости той же темы) — 2–4 пункта одной строкой.
Опирайся на посты; если событие в названии ФОМ шире одного эпизода, опиши его так же широко.

Посты:
{posts}
"""

if __name__ == "__main__":
    posts = C.R.load_posts()
    folder = C.OUT / "briefs" / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    schema = {"type": "object", "additionalProperties": False,
              "required": ["what_happened", "counts", "does_not_count"],
              "properties": {k: {"type": "string"} for k in ["what_happened", "counts", "does_not_count"]}}
    (C.OUT / "briefs" / "schema.json").write_text(json.dumps(schema, indent=2))
    for slug in C.EVENTS:
        e = C.event(slug)
        block = "\n\n".join(f"[{posts[i]['date'][:10]}] {posts[i]['text'][:500]}" for i in C.ranked_candidates(slug, 40))
        (folder / f"{slug}.txt").write_text(PROMPT.format(
            name=e["name"], week=e["week"], quotes="; ".join(e["quotes"]), lo=e["window"][0],
            hi=e["window"][1], posts=block), encoding="utf-8")
        print(slug)
