-- Starter query template for inspecting candidate messages around an event.
-- Replace the date range and keyword patterns before running.

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
