-- Where a theme or umbrella has exactly one event with a matched set, adding up "each post
-- once, over the union of window days" must give exactly that event's own numbers. Any
-- row returned is a group where the theme roll-up and the event disagree, which would mean
-- the de-duplication or the union-window denominator is wrong.

-- The test reads several models, so Dagster needs to be told which one to attach it to.
{{ config(meta={'dagster': {'ref': {'name': 'theme_group_coverage'}}}) }}

-- "Searched" means the event has a matched set in stg_event_datasets: those are the
-- windows the roll-up adds up.
with searched as (

    select 'theme' as scope_type, theme_id as scope_id, event_id
    from {{ ref('week_events') }}
    where theme_id is not null
      and event_id in (select event_id from {{ ref('stg_event_datasets') }})

    union all

    select 'umbrella', umbrella_id, event_id
    from {{ ref('week_events') }}
    where umbrella_id is not null
      and event_id in (select event_id from {{ ref('stg_event_datasets') }})

),

single as (

    select scope_type, scope_id, min(event_id) as event_id
    from searched
    group by 1, 2
    having count(*) = 1

),

rolled_up as (

    select
        single.event_id,
        coverage.media_group,
        coverage.distinct_matched_posts,
        coverage.posts_published_in_union_window
    from {{ ref('theme_group_coverage') }} as coverage
    inner join single using (scope_type, scope_id)

),

per_event as (

    select event_id, media_group, matched_posts, posts_published_in_window
    from {{ ref('event_group_coverage') }}
    where event_id in (select event_id from single)

)

select
    coalesce(rolled_up.event_id, per_event.event_id)        as event_id,
    coalesce(rolled_up.media_group, per_event.media_group)  as media_group,
    rolled_up.distinct_matched_posts,
    per_event.matched_posts,
    rolled_up.posts_published_in_union_window,
    per_event.posts_published_in_window
from rolled_up
full outer join per_event
    on  per_event.event_id = rolled_up.event_id
    and per_event.media_group = rolled_up.media_group
where rolled_up.event_id is null
   or per_event.event_id is null
   or rolled_up.distinct_matched_posts <> per_event.matched_posts
   or rolled_up.posts_published_in_union_window <> per_event.posts_published_in_window
