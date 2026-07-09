-- Starter query template for inspecting candidate messages around an event.
-- Replace the date range and keyword patterns before running.
--
-- CYRILLIC WARNING: SQLite lower() and LIKE are ASCII-only — lower('Курск') does NOT
-- lowercase Cyrillic, so lower(summary) LIKE '%курск%' silently misses «Курск».
-- For real keyword matching do it in Python (src/events_coverage/matching.py::keyword_match),
-- or pass every case variant of the keyword as a separate parameter here.
-- This template is for eyeballing samples, not for counting coverage.

select
    source,
    message_id,
    date,
    views,
    forwards,
    summary,
    original_message
from unified_messages
where date >= :match_start
  and date < :match_end
  and (
      lower(summary) like :keyword_1
      or lower(original_message) like :keyword_1
      or lower(summary) like :keyword_2
      or lower(original_message) like :keyword_2
  )
order by date asc
limit 500;
