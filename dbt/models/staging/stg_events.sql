-- One row per FOM weekly event, with the real calendar window worked out from the
-- year and week numbers.
--
-- Staging keeps the same number of rows as the source: nothing is filtered out
-- here. Rows that are not real events are flagged instead, so later models can
-- decide what to do with them and nothing disappears without a trace.

with source as (

    select * from {{ source('raw', 'fom_events') }}

),

cleaned as (

    select
        -- No identifier exists in the source. Year, week and event name together
        -- are unique across all rows, so their fingerprint is a safe stable id.
        md5(concat_ws('|', year::varchar, week::varchar, event))  as event_id,

        year                                                      as fom_year,
        week                                                      as fom_week,
        trim(event)                                               as event_name,
        description                                               as quote_examples,
        percentage                                                as attention_percentage,

        -- The 4th of January always falls in ISO week 1, and date_trunc('week', ...)
        -- moves a date back to its Monday. So this is the Monday of week 1, plus one
        -- whole week for every week since.
        (
            date_trunc('week', make_date(year, 1, 4))
            + (week - 1) * interval 7 day
        )::date                                                   as week_start

    from source

)

select
    event_id,
    fom_year,
    fom_week,
    event_name,
    quote_examples,
    attention_percentage,

    week_start,
    (week_start + interval 6 day)::date  as week_end,

    -- The search window used when matching posts to an event. It starts a few days
    -- before the survey week to catch early coverage and ends after it to catch
    -- delayed write-ups. match_end_exclusive is the first day NOT included, which is
    -- why it adds 6 days to reach Sunday, then the window days, then one more day.
    -- Same arithmetic as iso_week_window() in src/events_coverage/matching.py, so
    -- these windows line up with the matched post sets already built.
    (week_start - interval {{ var('event_window_days_before') }} day)::date  as match_start,
    (week_start + interval {{ var('event_window_days_after') + 7 }} day)::date
                                                                            as match_end_exclusive,

    -- Not every row names a specific event. Some are survey answer categories, and
    -- some are standing buckets FOM reuses week after week. Searching for posts about
    -- either would be meaningless, but they are real survey rows and their percentages
    -- are part of the weekly total, so they are labelled here and never dropped.
    case
        when event_name = 'Затрудняюсь ответить, нет ответа'
            then 'survey non-response'
        when event_name in (
            'Другие события в России',
            'Другие события в мире',
            'Работа властных структур'
        )   then 'catch-all category'
        else 'specific event'
    end  as event_kind

from cleaned
