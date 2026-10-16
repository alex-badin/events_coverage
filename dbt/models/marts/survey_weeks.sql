-- Grain: one calendar week, from the first FOM survey week to the last.
--
-- The dashboard's time axis. FOM did not publish every week — there are gaps around the
-- New Year and a few others — so the calendar is generated here rather than taken from
-- the survey, and has_survey says which weeks have a list. A week without a survey is a
-- gap on the axis, not a week in which nothing happened.
--
-- FOM numbers its weeks the ISO way (stg_events works week_start out from ISO week 1),
-- so a calendar week without a survey gets its ISO year and week number.

with events as (

    select * from {{ ref('week_events') }}

),

bounds as (

    select min(week_start) as first_week, max(week_start) as last_week
    from events

),

calendar as (

    select unnest(generate_series(first_week, last_week, interval 7 day))::date  as week_start
    from bounds

),

per_week as (

    select
        week_start,
        count(*) filter (where event_kind = 'specific event')                    as n_specific_events,
        count(*) filter (where coverage_status = 'measured')                     as n_measured_events,
        max(attention_percentage) filter (where event_kind = 'survey non-response')
                                                                                 as non_response_percentage
    from events
    group by 1

)

select
    calendar.week_start,
    (calendar.week_start + interval 6 day)::date        as week_end,
    isoyear(calendar.week_start)                        as fom_year,
    weekofyear(calendar.week_start)                     as fom_week,
    per_week.week_start is not null                     as has_survey,
    coalesce(per_week.n_specific_events, 0)             as n_specific_events,
    coalesce(per_week.n_measured_events, 0)             as n_measured_events,
    per_week.non_response_percentage

from calendar
left join per_week using (week_start)
