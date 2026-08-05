-- Grain: one media group per event.
--
-- The main table behind the dashboard. Every group that was publishing during the
-- event's window gets a row, including groups that published nothing about the event —
-- those rows carry zero matched posts and are what makes silence readable.

with source_window as (

    select * from {{ ref('int_event_source_window') }}

),

messages as (

    select * from {{ ref('int_event_messages') }}

),

events as (

    select * from {{ ref('stg_event_datasets') }}

),

-- Roll the per-source rows up to the group.
by_group as (

    select
        event_id,
        event_slug,
        media_group,
        media_group_key,

        count(*)                                            as sources_active,
        count(*) filter (where covered_event)               as sources_covering,
        sum(posts_published_in_window)                      as posts_published_in_window,
        sum(matched_posts)                                  as matched_posts,
        sum(digest_posts)                                   as digest_posts,
        min(first_matched_at)                               as first_matched_at,
        max(last_matched_at)                                as last_matched_at,
        sum(views_total)                                    as views_total,
        sum(forwards_total)                                 as forwards_total

    from source_window
    group by 1, 2, 3, 4

),

-- A couple of figures that need the individual posts rather than per-source totals.
per_post as (

    select
        event_id,
        media_group,
        median(views)                       as median_views_per_post,
        count(distinct published_date)      as days_with_coverage,
        avg(rerank_score)                   as mean_relevance_score

    from messages
    group by 1, 2

),

event_totals as (

    select
        event_id,
        sum(matched_posts)  as event_matched_posts

    from by_group
    group by 1

)

select
    by_group.event_id,
    by_group.event_slug,
    events.event_name,
    events.fom_year,
    events.fom_week,
    events.attention_percentage,
    events.match_start,
    events.match_end_exclusive,

    by_group.media_group,
    by_group.media_group_key,

    -- Volume
    by_group.matched_posts,
    by_group.digest_posts,
    by_group.sources_covering,
    by_group.sources_active,
    by_group.posts_published_in_window,

    by_group.matched_posts > 0                                      as covered_event,

    -- What share of all coverage of this event came from this group.
    case
        when event_totals.event_matched_posts > 0
        then by_group.matched_posts::double / event_totals.event_matched_posts
    end                                                             as share_of_voice,

    -- How many of the group's own active sources said anything at all.
    by_group.sources_covering::double / by_group.sources_active     as source_coverage_rate,

    -- How much of the group's own output went to this event. This is the figure that
    -- stops the largest publishers from automatically looking the most interested:
    -- a group posting 40 times out of 200 posts is more focused on the event than a
    -- group posting 60 times out of 6,000.
    case
        when by_group.posts_published_in_window > 0
        then 1000.0 * by_group.matched_posts / by_group.posts_published_in_window
    end                                                             as matched_posts_per_1000_published,

    -- Timing, measured from the moment the window opens, which is the same instant for
    -- every group, so the numbers are comparable across groups.
    by_group.first_matched_at,
    by_group.last_matched_at,
    date_diff('hour', events.match_start::timestamp, by_group.first_matched_at)  as coverage_lag_hours,
    per_post.days_with_coverage,

    -- 1 = this group published about the event before any other group did.
    case
        when by_group.first_matched_at is not null
        then dense_rank() over (
            partition by by_group.event_id
            order by by_group.first_matched_at
        )
    end                                                             as first_mention_rank,

    -- Reach. The view counter is present on every matched post; the forward counter is
    -- missing on some, so forwards_total is a sum over the posts that have it.
    by_group.views_total,
    by_group.forwards_total,
    per_post.median_views_per_post,
    case
        when by_group.matched_posts > 0
        then by_group.views_total::double / by_group.matched_posts
    end                                                             as views_per_matched_post,

    -- Average relevance score of this group's matched posts. A low value warns that the
    -- group's matches are weaker and worth reading before quoting the count.
    per_post.mean_relevance_score

from by_group
inner join events       on by_group.event_id = events.event_id
inner join event_totals on by_group.event_id = event_totals.event_id
left join per_post
    on  by_group.event_id    = per_post.event_id
    and by_group.media_group = per_post.media_group
