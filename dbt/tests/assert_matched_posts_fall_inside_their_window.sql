-- No matched post may be dated outside the search window it was matched in. A post
-- outside the window means the window arithmetic in stg_events and the window recorded
-- by the matching run have drifted apart, which would quietly break every timing
-- measure — first mention, lag, and the daily timeline.

select
    event_id,
    event_slug,
    source_name,
    message_id,
    published_date,
    match_start,
    match_end_exclusive

from {{ ref('int_event_messages') }}
where published_date <  match_start
   or published_date >= match_end_exclusive
