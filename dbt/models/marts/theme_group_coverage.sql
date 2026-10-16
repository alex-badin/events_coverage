-- Grain: one scope (a theme, an umbrella, or everything) and one media group.
--
-- Coverage added up over several measured events, done so that nothing is counted twice.
-- Two traps make the naive sum wrong:
--   * Search windows of neighbouring survey weeks overlap (each runs from 3 days before
--     the week to 10 days after it), and the same post can be matched to both events.
--     So posts are counted once per scope, by source and message id.
--   * The denominator — everything the group published — would be counted twice on the
--     overlapping days too. So it is taken over the union of the window days: every
--     calendar day covered by at least one of the scope's measured windows, once.
-- A scope with one measured event therefore gives exactly that event's numbers, which
-- tests/assert_theme_coverage_matches_single_event.sql checks.
--
-- Only scopes with at least one measured event appear. Groups that published in the
-- union window but matched nothing appear with zero, as in every other coverage mart.

with events as (

    select * from {{ ref('week_events') }}
    where event_kind = 'specific event'

),

scope_events as (

    select 'theme' as scope_type, theme_id as scope_id, event_id, coverage_status
    from events where theme_id is not null

    union all

    select 'umbrella', umbrella_id, event_id, coverage_status
    from events where umbrella_id is not null

    union all

    select 'all', 'all', event_id, coverage_status
    from events

),

scope_counts as (

    select
        scope_type,
        scope_id,
        count(*)                                                as n_events,
        count(*) filter (where coverage_status = 'measured')    as n_measured_events
    from scope_events
    group by 1, 2

),

measured as (

    select
        scope_events.scope_type,
        scope_events.scope_id,
        datasets.event_id,
        datasets.match_start,
        datasets.match_end_exclusive
    from scope_events
    inner join {{ ref('stg_event_datasets') }} as datasets using (event_id)

),

union_days as (

    select distinct scope_type, scope_id, activity_date
    from (
        select
            scope_type,
            scope_id,
            unnest(generate_series(
                match_start::timestamp,
                (match_end_exclusive - 1)::timestamp,
                interval 1 day
            ))::date  as activity_date
        from measured
    )

),

window_length as (

    select scope_type, scope_id, count(*) as union_window_days
    from union_days
    group by 1, 2

),

published as (

    select
        union_days.scope_type,
        union_days.scope_id,
        groups.media_group,
        groups.media_group_key,
        count(distinct activity.source_name)    as sources_active,
        sum(activity.post_count)                as posts_published_in_union_window
    from union_days
    inner join {{ ref('stg_source_activity') }} as activity
        on activity.activity_date = union_days.activity_date
    inner join {{ ref('stg_media_groups') }} as groups
        on groups.source_name = activity.source_name
    group by 1, 2, 3, 4

),

matched as (

    select
        measured.scope_type,
        measured.scope_id,
        messages.media_group,
        count(distinct concat_ws(':', messages.source_name, messages.message_id))
                                                as distinct_matched_posts,
        count(distinct messages.source_name)    as sources_covering
    from measured
    inner join {{ ref('int_event_messages') }} as messages using (event_id)
    group by 1, 2, 3

)

select
    published.scope_type,
    published.scope_id,
    published.media_group,
    published.media_group_key,
    scope_counts.n_events,
    scope_counts.n_measured_events,
    coalesce(matched.distinct_matched_posts, 0)   as distinct_matched_posts,
    coalesce(matched.sources_covering, 0)         as sources_covering,
    published.sources_active,
    window_length.union_window_days,
    published.posts_published_in_union_window,
    case
        when published.posts_published_in_union_window > 0
        then 1000.0 * coalesce(matched.distinct_matched_posts, 0)
             / published.posts_published_in_union_window
    end                                           as matched_posts_per_1000_published

from published
inner join scope_counts using (scope_type, scope_id)
inner join window_length using (scope_type, scope_id)
left join matched using (scope_type, scope_id, media_group)
