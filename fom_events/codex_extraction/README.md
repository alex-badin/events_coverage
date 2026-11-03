# FOM event lists extracted with Codex

`out/<report>.json` — the event list of each FOM report that `processed_events.json` did not have
before 2026-11-03 (77 reports, 2025-W12 to 2026-W43), as extracted by `../extract_events_codex.py`.

- Extracted 2026-11-03 with OpenAI Codex (`codex-cli 0.160.0`, model `gpt-6.1-sol`, reasoning effort
  `medium`, second account, subscription), through `exploration/2026-10-17_jev_selection/codex_answer.sh`.
- Prompt: `prompt_detailed` of `../config.yaml` plus the reading note in `extract_events_codex.py`
  (`HOW_TO_READ`), then the report's text boxes with position and bold from `pdftohtml -xml`.
  `prompts/` is rebuilt by `python extract_events_codex.py prompts <file.pdf ...>`; not in git.
- Check before use: on four reports Gemini had already parsed (2021-W19, 2023-W06, 2025-W10,
  2025-W11) Codex returned the same 51 event names, quote counts and percentages, except one
  percentage (2025-W10, «СВО в целом»: Codex 16, the sub-event's own number; Gemini 18, the parent
  event's total), where Codex is right.
- Survey week: every report's printed survey dates fall in the week of its address number
  (`extract_events_codex.py check`). d51sn2025 ran 19–22 December 2025, Friday to Monday: three of
  its four days are in ISO week 51, so it stays 2025-W51.
- Missing from FOM's site (no file at either address form): 2025-W19, 2025-W52, 2026-W1–2,
  2026-W19, 2026-W30, 2026-W38.
