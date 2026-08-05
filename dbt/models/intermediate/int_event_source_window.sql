-- Grain: one source per event — every source that was publishing anything during the
-- event's window, whether or not it covered the event.
--
-- Why this model exists: a bar chart of matched-post counts cannot tell the difference
-- between a group that chose not to cover an event and a group that was not publishing
-- at all in that period. Starting from all active sources and then attaching the
-- matched counts keeps that difference visible, and it gives every "share of own
-- output" figure an honest denominator.

with events as (

    select * from {{ ref('stg_event_datasets') }}

),

activity as (

    select * from {{ ref('stg_source_activity') }}

),

groups as (

    select * from {{ ref('stg_media_groups') }}

),

-- Total posts each source published inside each event's window, on any topic.
window_activity as (

    select
        events.event_id,
        events.event_slug,
        activity.source_name,
        sum(activity.post_count)  as posts_published_in_window,
        count(*)                  as active_days_in_window

    from events
    inner join activity
        on activity.activity_date >= events.match_start
       and activity.activity_date <  events.match_end_exclusive
    group by 1, 2, 3

),

-- What each source published about the event itself.
window_matches as (

    select
        event_id,
        source_name,
        count(*)                          as matched_posts,
        min(published_at)                 as first_matched_at,
        max(published_at)                 as last_matched_at,
        sum(views)                        as views_total,
        sum(forwards)                     as forwards_total,
        sum(case when is_digest then 1 else 0 end)  as digest_posts

    from {{ ref('int_event_messages') }}
    group by 1, 2

)

select
    window_activity.event_id,
    window_activity.event_slug,
    window_activity.source_name,

    -- Same fallback as int_event_messages: a label the accepted_values test rejects, so
    -- an unexpected source breaks the build instead of quietly forming its own bucket.
    coalesce(groups.media_group, 'Ungrouped source (unexpected)')  as media_group,
    coalesce(groups.media_group_key, 'ungrouped_unexpected')       as media_group_key,

    window_activity.posts_published_in_window,
    window_activity.active_days_in_window,

    coalesce(window_matches.matched_posts, 0)   as matched_posts,
    coalesce(window_matches.digest_posts, 0)    as digest_posts,
    window_matches.first_matched_at,
    window_matches.last_matched_at,
    window_matches.views_total,
    window_matches.forwards_total,

    window_matches.matched_posts is not null    as covered_event

from window_activity
left join window_matches
    on  window_activity.event_id   = window_matches.event_id
    and window_activity.source_name = window_matches.source_name
left join groups
    on window_activity.source_name = groups.source_name
