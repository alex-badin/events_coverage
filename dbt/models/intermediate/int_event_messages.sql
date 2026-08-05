-- Grain: one matched post seen in the context of one event.
--
-- This is the working table the coverage marts are built from. It brings together the
-- three things a coverage number needs: the post, the media group that published it,
-- and where the post sits inside the event's search window.

with matches as (

    select * from {{ ref('stg_event_matches') }}

),

events as (

    select * from {{ ref('stg_event_datasets') }}

),

groups as (

    select * from {{ ref('stg_media_groups') }}

)

select
    matches.event_id,
    matches.event_slug,
    events.event_name,
    events.fom_year,
    events.fom_week,
    events.attention_percentage,
    events.match_start,
    events.match_end_exclusive,

    matches.source_name,

    -- Every source in the matched sets belongs to a group: the loader drops archived
    -- sources, and the other 56 are all in the map. The fallback label is deliberately
    -- one the `accepted_values` test rejects, so a source that slips through fails the
    -- build loudly instead of hiding in a bucket nobody reads.
    coalesce(groups.media_group, 'Ungrouped source (unexpected)')  as media_group,
    coalesce(groups.media_group_key, 'ungrouped_unexpected')       as media_group_key,

    matches.message_id,
    matches.published_at,
    matches.published_date,

    -- How long after the window opened this post appeared. The window opens a few days
    -- before the survey week, so this is the same starting line for every group.
    date_diff('hour', events.match_start::timestamp, matches.published_at)  as hours_from_window_start,
    date_diff('day', events.match_start, matches.published_date)            as days_from_window_start,

    matches.is_digest,
    matches.views,
    matches.forwards,
    matches.rerank_score,
    matches.keyword_match,

    matches.summary,
    matches.original_message

from matches
inner join events on matches.event_id = events.event_id
left join groups on matches.source_name = groups.source_name
