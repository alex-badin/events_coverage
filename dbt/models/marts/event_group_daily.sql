-- Grain: one media group per day per event, for every day of the event window.
--
-- Days with no coverage are present as zero rows, not missing rows. A timeline drawn
-- from rows that only exist when something happened joins across the gaps and hides
-- exactly the silences this project is about.

with events as (

    select * from {{ ref('stg_event_datasets') }}

),

messages as (

    select * from {{ ref('int_event_messages') }}

),

-- The groups that were publishing during each event's window — the rows a complete
-- timeline needs, coverage or not.
active_groups as (

    select distinct
        event_id,
        event_slug,
        media_group,
        media_group_key

    from {{ ref('int_event_source_window') }}

),

window_days as (

    select
        events.event_id,
        unnest(
            generate_series(
                events.match_start,
                events.match_end_exclusive - interval 1 day,
                interval 1 day
            )
        )::date  as coverage_date

    from events

),

scaffold as (

    select
        active_groups.event_id,
        active_groups.event_slug,
        active_groups.media_group,
        active_groups.media_group_key,
        window_days.coverage_date

    from active_groups
    inner join window_days on active_groups.event_id = window_days.event_id

),

daily as (

    select
        event_id,
        media_group,
        published_date,
        count(*)        as matched_posts,
        sum(views)      as views_total,
        sum(forwards)   as forwards_total

    from messages
    group by 1, 2, 3

)

select
    scaffold.event_id,
    scaffold.event_slug,
    scaffold.media_group,
    scaffold.media_group_key,
    scaffold.coverage_date,

    coalesce(daily.matched_posts, 0)  as matched_posts,
    daily.views_total,
    daily.forwards_total

from scaffold
left join daily
    on  scaffold.event_id       = daily.event_id
    and scaffold.media_group    = daily.media_group
    and scaffold.coverage_date  = daily.published_date
