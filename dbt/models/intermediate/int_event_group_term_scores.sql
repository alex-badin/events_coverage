{{ config(materialized='table') }}

-- Grain: one word or two-word phrase, per media group, per event, for the terms that pass the
-- filters described at the top of event_group_terms. Numbers only: the words themselves and the
-- lists of posts are added there, once this table has shrunk 31 million group-level terms to
-- the few that survive. Doing both in one query ran out of memory at a 6 GB limit.

{% set smoothing = 0.02 %}
{% set min_posts_with_term = 3 %}
{% set min_group_posts = 10 %}
{% set min_event_specificity = 0.4 %}
{% set max_top_source_share = 0.7 %}

with source_terms as (

    select * from {{ ref('int_event_source_terms') }}

),

posts as (

    select * from {{ ref('int_event_posts_with_words') }}

),

-- The two matching methods are never compared (see AGENTS.md), so "the other events" of an
-- event means the other events matched the same way.
event_groups as (

    select distinct
        event_hash,
        group_hash,
        event_id,
        event_slug,
        media_group,
        media_group_key,
        event_slug like '%\_fulltext' escape '\'  as is_full_text_match
    from posts

),

-- How many posts each group contributed to each event, and how many sources those came
-- from. The denominator for every share below.
group_post_counts as (

    select
        event_hash,
        group_hash,
        count(*)  as group_posts,
        count(distinct source_hash)  as group_sources

    from posts
    group by 1, 2

),

-- How many posts each individual channel contributed to each event.
source_post_counts as (

    select
        event_hash,
        source_hash,
        count(*)  as source_posts

    from posts
    group by 1, 2

),

-- Roll the per-source counts up to the group. The largest share the term takes of any one
-- channel's posts is kept as a diagnostic: it is how you check, from the table alone,
-- whether a surprising term is a group habit or one channel's tic.
all_terms as (

    select
        source_terms.event_hash,
        source_terms.group_hash,
        source_terms.term_hash,

        sum(source_terms.posts_with_term)   as posts_with_term,
        count(*)                            as sources_with_term,
        sum(source_terms.term_uses)         as term_uses,

        max(
            source_terms.posts_with_term::double / source_post_counts.source_posts
        )  as max_share_within_one_source,

        -- What share of the posts carrying this term came from its single busiest channel.
        -- Near 1 means one channel is doing all the talking and the rest are reposting it.
        max(source_terms.posts_with_term)::double
            / nullif(sum(source_terms.posts_with_term), 0)  as top_source_share_of_term

    from source_terms
    inner join source_post_counts
        on  source_terms.event_hash  = source_post_counts.event_hash
        and source_terms.source_hash = source_post_counts.source_hash
    group by 1, 2, 3

),

-- The same term across the whole event, so each group can be compared with everyone else.
event_term_totals as (

    select
        event_hash,
        term_hash,
        sum(posts_with_term)  as event_posts_with_term

    from all_terms
    group by 1, 2

),

-- The same term across everything the same group said about the *other* events. This is
-- what tells a word the event brought in apart from a word the group always uses.
group_term_totals as (

    select
        event_groups.group_hash,
        event_groups.is_full_text_match,
        all_terms.term_hash,
        sum(all_terms.posts_with_term)  as group_posts_with_term_all_events

    from all_terms
    inner join event_groups
        on  all_terms.event_hash = event_groups.event_hash
        and all_terms.group_hash = event_groups.group_hash
    group by 1, 2, 3

),

group_totals as (

    select
        event_groups.group_hash,
        event_groups.is_full_text_match,
        sum(group_post_counts.group_posts)  as group_posts_all_events

    from group_post_counts
    inner join event_groups
        on  group_post_counts.event_hash = event_groups.event_hash
        and group_post_counts.group_hash = event_groups.group_hash
    group by 1, 2

),

event_post_counts as (

    select event_hash, sum(group_posts) as event_posts
    from group_post_counts
    group by 1

),

compared as (

    select
        all_terms.event_hash,
        all_terms.group_hash,
        all_terms.term_hash,
        all_terms.posts_with_term,
        all_terms.sources_with_term,
        all_terms.term_uses,
        all_terms.max_share_within_one_source,
        all_terms.top_source_share_of_term,

        group_post_counts.group_posts,
        group_post_counts.group_sources,

        event_term_totals.event_posts_with_term - all_terms.posts_with_term  as other_posts_with_term,
        event_post_counts.event_posts - group_post_counts.group_posts        as other_posts,

        all_terms.posts_with_term::double / group_post_counts.group_posts    as share_in_group,

        -- Everyone else, same event.
        case
            when event_post_counts.event_posts - group_post_counts.group_posts > 0
            then (event_term_totals.event_posts_with_term - all_terms.posts_with_term)::double
                 / (event_post_counts.event_posts - group_post_counts.group_posts)
        end  as share_elsewhere,

        -- Same group, the other events.
        case
            when group_totals.group_posts_all_events - group_post_counts.group_posts > 0
            then (group_term_totals.group_posts_with_term_all_events - all_terms.posts_with_term)::double
                 / (group_totals.group_posts_all_events - group_post_counts.group_posts)
        end  as share_in_group_other_events

    from all_terms
    inner join event_groups
        on  all_terms.event_hash = event_groups.event_hash
        and all_terms.group_hash = event_groups.group_hash
    inner join group_post_counts
        on  all_terms.event_hash = group_post_counts.event_hash
        and all_terms.group_hash = group_post_counts.group_hash
    inner join event_term_totals
        on  all_terms.event_hash = event_term_totals.event_hash
        and all_terms.term_hash  = event_term_totals.term_hash
    inner join group_term_totals
        on  all_terms.group_hash            = group_term_totals.group_hash
        and all_terms.term_hash             = group_term_totals.term_hash
        and event_groups.is_full_text_match = group_term_totals.is_full_text_match
    inner join group_totals
        on  all_terms.group_hash            = group_totals.group_hash
        and event_groups.is_full_text_match = group_totals.is_full_text_match
    inner join event_post_counts
        on all_terms.event_hash = event_post_counts.event_hash

    where all_terms.posts_with_term     >= {{ min_posts_with_term }}
      and group_post_counts.group_posts >= {{ min_group_posts }}
      -- Used by more than one channel in the group, unless the group only has one channel
      -- covering the event at all.
      and all_terms.sources_with_term   >= least(2, group_post_counts.group_sources)
      -- Not one channel's boilerplate carried into its neighbours by reposting. Only
      -- applied where the group has enough channels for the share to mean anything.
      and (
            group_post_counts.group_sources < 3
            or all_terms.top_source_share_of_term <= {{ max_top_source_share }}
          )

),

scored as (

    select
        *,

        -- How much more often this group's posts carry the term than everyone else's, on a
        -- doubling scale: 1 means twice as often, 2 means four times, -1 means half as
        -- often. Both shares get {{ smoothing }} added first, so a term in three posts and
        -- nowhere else scores high but not infinitely high.
        log2(
            (share_in_group + {{ smoothing }})
            / (coalesce(share_elsewhere, 0) + {{ smoothing }})
        )  as distinctiveness,

        -- The same scale, comparing this event with the group's coverage of the others.
        -- Channel furniture sits near zero here because it appears everywhere equally.
        log2(
            (share_in_group + {{ smoothing }})
            / (coalesce(share_in_group_other_events, 0) + {{ smoothing }})
        )  as event_specificity

    from compared

),

-- The term has to be one this event brought in, not one the group always uses.
kept as (

    select * from scored
    where event_specificity >= {{ min_event_specificity }}

)

select * from kept
