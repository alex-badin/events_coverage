-- Grain: one media group per event, comparing events with each other.
--
-- The other coverage models answer "inside this event, who covered it most". This one
-- answers a different question: which events landed with which kinds of media, and with
-- their audiences, compared with how that group normally behaves.
--
-- Why a plain post count cannot answer it: state agencies publish more than war channels
-- on every event, so state agencies would top every event and the table would say nothing.
-- What is informative is whether a group took a *bigger slice of this event than it
-- usually takes* — that is what the three comparisons below measure. Each is a ratio
-- against the same group's own average across all loaded events, so 1.0 means "exactly as
-- usual", 2.0 means "twice its usual", and 0 means it stayed out of this one.
--
-- Read with care while the event set is small: the "usual" for each group is an average
-- over the loaded events only, so every event is part of the baseline it is compared to.
-- With six events the ratios are indicative, not settled.

with coverage as (

    select * from {{ ref('event_group_coverage') }}

),

events as (

    select * from {{ ref('event_overview') }}

),

-- What "usual" means for each group: its totals summed over every loaded event.
group_baseline as (

    select
        media_group,

        sum(matched_posts)                          as baseline_matched_posts,
        sum(posts_published_in_window)              as baseline_posts_published,
        sum(views_total)                            as baseline_views_total,

        -- Its usual slice of coverage, across all events pooled together.
        sum(matched_posts)::double
            / nullif(sum(sum(matched_posts)) over (), 0)   as baseline_share_of_voice,

        -- Its usual rate of covering a matched event, per thousand posts it publishes.
        case
            when sum(posts_published_in_window) > 0
            then 1000.0 * sum(matched_posts) / sum(posts_published_in_window)
        end                                         as baseline_per_1000_published,

        -- The views its matched posts usually get.
        case
            when sum(matched_posts) > 0
            then sum(views_total)::double / sum(matched_posts)
        end                                         as baseline_views_per_post

    from coverage
    group by 1

),

event_views as (

    select
        event_id,
        sum(views_total)  as event_views_total

    from coverage
    group by 1

)

select
    coverage.event_id,
    coverage.event_slug,
    coverage.event_name,
    coverage.fom_year,
    coverage.fom_week,
    coverage.attention_percentage,
    coverage.match_start,

    coverage.media_group,
    coverage.media_group_key,

    -- The raw figures the ratios are built from, so nothing below is unexplainable.
    coverage.matched_posts,
    coverage.posts_published_in_window,
    coverage.share_of_voice,
    coverage.matched_posts_per_1000_published,
    coverage.views_total,
    coverage.views_per_matched_post,

    group_baseline.baseline_share_of_voice,
    group_baseline.baseline_per_1000_published,
    group_baseline.baseline_views_per_post,

    -- (1) Slice of this event's coverage, against the slice this group usually takes.
    -- Above 1: the group leaned into this event more than it leans into events generally.
    coverage.share_of_voice
        / nullif(group_baseline.baseline_share_of_voice, 0)   as coverage_lift,

    -- (2) The same idea measured against the group's own output rather than against the
    -- other groups. Above 1: a larger part of what this group published was about this
    -- event than is normal for it. This one does not move when other groups go quiet.
    coverage.matched_posts_per_1000_published
        / nullif(group_baseline.baseline_per_1000_published, 0)  as effort_lift,

    -- (3) The audience side: did posts about this event get more views than this group's
    -- matched posts usually get? Null where the group published nothing about the event.
    coverage.views_per_matched_post
        / nullif(group_baseline.baseline_views_per_post, 0)   as audience_lift,

    -- Share of all the views this event's coverage collected, so the audience side also
    -- has a plain "whose readers saw it" number and not only a ratio.
    coverage.views_total::double
        / nullif(event_views.event_views_total, 0)            as share_of_event_views,

    -- A readable label for comparison (1), on the same cuts the dashboard colours by.
    case
        when coverage.matched_posts = 0 then 'stayed out of it'
        when coverage.share_of_voice / nullif(group_baseline.baseline_share_of_voice, 0) >= 1.5
            then 'much more than usual'
        when coverage.share_of_voice / nullif(group_baseline.baseline_share_of_voice, 0) >= 1.15
            then 'more than usual'
        when coverage.share_of_voice / nullif(group_baseline.baseline_share_of_voice, 0) <= 0.67
            then 'much less than usual'
        when coverage.share_of_voice / nullif(group_baseline.baseline_share_of_voice, 0) <= 0.87
            then 'less than usual'
        else 'about as usual'
    end                                                       as coverage_lift_label

from coverage
inner join group_baseline on coverage.media_group = group_baseline.media_group
inner join events         on coverage.event_id    = events.event_id
left join event_views     on coverage.event_id    = event_views.event_id
