-- The share of a window the search could see is a share: between 0 and 1. It once came out
-- at 1.03-1.04 for every event, because the search pool counted archived sources and the
-- denominator did not. Returns any event whose share leaves that range.
--
-- A test passes when it returns no rows.

select event_id, event_slug, searchable_share_of_window
from {{ ref('event_overview') }}
where searchable_share_of_window < 0
   or searchable_share_of_window > 1
