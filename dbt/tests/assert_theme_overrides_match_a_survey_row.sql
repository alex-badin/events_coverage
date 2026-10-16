-- Every week-level theme override must point at a real survey row. An override whose year,
-- week or wording has a typo would otherwise match nothing and silently do nothing.
--
-- A test passes when it returns no rows.

-- The test reads several models, so Dagster needs to be told which one to attach it to.
{{ config(meta={'dagster': {'ref': {'name': 'fom_event_week_themes'}}}) }}

select overrides.*
from {{ ref('fom_event_week_themes') }} as overrides
left join {{ ref('stg_events') }} as events
    on  events.fom_year = overrides.fom_year
    and events.fom_week = overrides.fom_week
    and events.event_name = overrides.event_name
where events.event_id is null
