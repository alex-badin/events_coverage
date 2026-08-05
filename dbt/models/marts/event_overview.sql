-- Grain: one event.
--
-- The event list the dashboard opens with: how much public attention the event got,
-- how much coverage it received, how wide that coverage was, and how the matched set
-- was produced.

with messages as (

    select * from {{ ref('int_event_messages') }}

),

source_window as (

    select * from {{ ref('int_event_source_window') }}

),

events as (

    select * from {{ ref('stg_event_datasets') }}

),

coverage as (

    select
        event_id,
        count(*)                                as matched_posts,
        count(distinct source_name)             as sources_covering,
        count(distinct media_group)             as groups_covering,
        min(published_at)                       as first_matched_at,
        max(published_at)                       as last_matched_at,
        count(distinct published_date)          as days_with_coverage,
        sum(views)                              as views_total,
        sum(forwards)                           as forwards_total,
        median(views)                           as median_views_per_post,
        median(rerank_score)                    as median_relevance_score,
        min(rerank_score)                       as min_relevance_score,
        sum(case when is_digest then 1 else 0 end)      as digest_posts,
        sum(case when keyword_match then 1 else 0 end)  as posts_with_keyword_anchor

    from messages
    group by 1

),

universe as (

    select
        event_id,
        count(*)                        as sources_active,
        count(distinct media_group)     as groups_active,
        sum(posts_published_in_window)  as posts_published_in_window

    from source_window
    group by 1

),

-- The single busiest day of coverage, useful for spotting whether an event was one
-- news spike or a story that stayed alive for a week.
peak_day as (

    select event_id, published_date, matched_posts
    from (
        select
            event_id,
            published_date,
            count(*)  as matched_posts,
            row_number() over (
                partition by event_id
                order by count(*) desc, published_date
            ) as day_rank
        from messages
        group by 1, 2
    )
    where day_rank = 1

)

select
    events.event_id,
    events.event_slug,
    events.event_name,
    events.fom_year,
    events.fom_week,
    events.attention_percentage,
    events.fom_quotes,

    events.match_start,
    events.match_end_exclusive,
    date_diff('day', events.match_start, events.match_end_exclusive)  as window_days,

    -- Coverage volume and breadth
    coverage.matched_posts,
    coverage.digest_posts,
    coverage.sources_covering,
    universe.sources_active,
    coverage.groups_covering,
    universe.groups_active,
    universe.posts_published_in_window,
    coverage.sources_covering::double / universe.sources_active  as source_coverage_rate,
    case
        when universe.posts_published_in_window > 0
        then 1000.0 * coverage.matched_posts / universe.posts_published_in_window
    end                                                          as matched_posts_per_1000_published,

    -- Timing
    coverage.first_matched_at,
    coverage.last_matched_at,
    coverage.days_with_coverage,
    peak_day.published_date   as peak_coverage_date,
    peak_day.matched_posts    as peak_coverage_posts,

    -- Reach
    coverage.views_total,
    coverage.forwards_total,
    coverage.median_views_per_post,

    -- How the matched set was produced. Kept beside the counts on purpose: a count is
    -- only as good as the retrieval and relevance threshold that produced it.
    events.retriever,
    events.embed_model,
    events.rerank_model,
    events.rerank_threshold,
    events.candidates_reranked,
    coverage.posts_with_keyword_anchor,
    coverage.median_relevance_score,
    coverage.min_relevance_score,

    -- The two things that can make an event's counts untrustworthy are different
    -- problems, so they are measured separately rather than blended into one flag.

    -- First: was the relevance bar set where the other events set it? A lower cut-off
    -- admits weaker matches, so the count is inflated relative to the rest.
    events.rerank_threshold = 0.35   as standard_relevance_cutoff,

    -- Second: could the search see the whole window? Posts without an embedding vector
    -- were never eligible to be found, so where this share is well under 1 the coverage
    -- is an undercount — and a group that looks silent may simply have been unsearchable.
    events.searchable_posts_in_window,
    case
        when universe.posts_published_in_window > 0
        then events.searchable_posts_in_window::double / universe.posts_published_in_window
    end                              as searchable_share_of_window,

    events.built_at

from events
left join coverage  on events.event_id = coverage.event_id
left join universe  on events.event_id = universe.event_id
left join peak_day  on events.event_id = peak_day.event_id
