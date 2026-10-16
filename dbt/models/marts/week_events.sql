-- Grain: one row of a FOM weekly survey list.
--
-- Every survey week, every row — specific events, FOM's catch-all categories and the
-- non-response line — because together they are what people said that week. Most rows
-- have no matched post set yet: building one is paid and curated, so coverage arrives
-- event by event. coverage_status says which rows have one, and the dashboard shows the
-- rest as "not measured yet" rather than as zero coverage.

with events as (

    select * from {{ ref('int_events_with_themes') }}

),

built as (

    select
        event_id,
        event_slug,
        matched_posts,
        groups_covering,
        groups_active
    from {{ ref('event_overview') }}

),

labels as (

    select * from {{ ref('event_labels_en') }}

),

empty_searches as (

    select event_id, event_slug from {{ ref('stg_empty_event_searches') }}

)

select
    events.event_id,
    events.fom_year,
    events.fom_week,
    events.week_start,
    events.week_end,
    events.event_name,
    events.event_kind,
    events.attention_percentage,
    events.quote_examples,

    -- Position in that week's list, counting specific events only. The catch-all and
    -- non-response rows get no rank, so "the week's top event" is always a real event.
    case
        when events.event_kind = 'specific event'
        then row_number() over (
            partition by events.week_start, events.event_kind = 'specific event'
            order by events.attention_percentage desc nulls last, events.event_name
        )
    end                                     as rank_in_week,

    events.theme_id,
    events.theme_label,
    events.umbrella_id,
    events.umbrella_label,

    -- Three different answers, kept apart: a matched set exists and has posts; a set was
    -- built but no post passed the relevance cut-off (a retrieval result, not silence);
    -- or nobody has built one yet.
    case
        when built.event_id is not null and coalesce(built.matched_posts, 0) > 0
                                            then 'measured'
        when built.event_id is not null or empty_searches.event_id is not null
                                            then 'no post passed the cut-off'
        else 'not measured'
    end                                     as coverage_status,

    coalesce(built.event_slug, empty_searches.event_slug)  as event_slug,
    labels.label_en                         as event_label_en,
    built.matched_posts,
    built.groups_covering,
    built.groups_active

from events
left join built using (event_id)
left join labels on labels.event_slug = built.event_slug
left join empty_searches using (event_id)
