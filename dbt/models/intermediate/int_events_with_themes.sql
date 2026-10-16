-- Grain: one FOM survey row, with the cross-week theme of its event.
--
-- A theme is a subject that recurs across survey weeks — prices, the war, Russia–US
-- relations — so that one subject can be followed over time even though FOM words it
-- differently from year to year. The seeds hold the theme list and which theme each FOM
-- wording belongs to; how that assignment was made and checked is written up in
-- dbt/seeds/README.md.
--
-- A theme is given per wording, which is right for nearly every row. A few generic FOM
-- rubrics («Праздники, памятные даты», «Стихийные бедствия») hold a different subject in
-- one particular week; fom_event_week_themes overrides the theme for exactly those weeks,
-- with the reason written next to each.
--
-- Only specific events get a theme. FOM's catch-all categories and the non-response line
-- are not subjects, so their theme stays empty.

with events as (

    select * from {{ ref('stg_events') }}

),

event_themes as (

    select * from {{ ref('fom_event_themes') }}

),

week_overrides as (

    select * from {{ ref('fom_event_week_themes') }}

),

themes as (

    select * from {{ ref('fom_themes') }}

)

select
    events.*,
    themes.theme_id,
    themes.theme_label,
    themes.umbrella_id,
    themes.umbrella_label,
    themes.theme_order,
    themes.umbrella_order

from events
left join event_themes
    on  events.event_kind = 'specific event'
    and event_themes.event_name = events.event_name
left join week_overrides
    on  week_overrides.fom_year = events.fom_year
    and week_overrides.fom_week = events.fom_week
    and week_overrides.event_name = events.event_name
left join themes
    on themes.theme_id = coalesce(week_overrides.theme_id, event_themes.theme_id)
