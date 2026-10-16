-- Grain: one theme in one survey week (only weeks in which the theme had an event).
--
-- How much of the week's survey answers went to a theme. When several of a week's events
-- share a theme their shares are added, and that sum is NOT a share of people: one
-- respondent can name two events of the same theme and is then counted twice. So the
-- dashboard calls it "mentions per 100 respondents", never a percentage of people.
-- The page adds themes up to umbrellas itself, under the same rule.

with events as (

    select *
    from {{ ref('week_events') }}
    where event_kind = 'specific event'
      and theme_id is not null

),

themes as (

    select * from {{ ref('fom_themes') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by theme_id, week_start
            order by attention_percentage desc nulls last, event_name
        )  as rank_in_theme_week
    from events

),

per_theme_week as (

    select
        theme_id,
        week_start,
        min(fom_year)                                               as fom_year,
        min(fom_week)                                               as fom_week,
        sum(attention_percentage)                                   as attention_sum,
        count(*)                                                    as n_events,
        count(*) filter (where coverage_status = 'measured')        as n_measured_events,
        max(event_name) filter (where rank_in_theme_week = 1)       as top_event_name,
        max(attention_percentage) filter (where rank_in_theme_week = 1)
                                                                    as top_event_share,
        -- Events sharing the top share. Above 1, top_event_name is one of a tie (the first
        -- alphabetically), and the page says "joint top".
        count(*) filter (where attention_percentage = top_share)    as n_top_events
    from (
        select *, max(attention_percentage) over (partition by theme_id, week_start) as top_share
        from ranked
    )
    group by 1, 2

)

select
    themes.umbrella_id,
    themes.umbrella_label,
    themes.umbrella_order,
    themes.theme_id,
    themes.theme_label,
    themes.theme_order,
    themes.is_other_theme,
    per_theme_week.week_start,
    per_theme_week.fom_year,
    per_theme_week.fom_week,
    per_theme_week.attention_sum,
    per_theme_week.n_events,
    per_theme_week.top_event_name,
    per_theme_week.top_event_share,
    per_theme_week.n_top_events,
    per_theme_week.n_measured_events

from per_theme_week
inner join themes using (theme_id)
