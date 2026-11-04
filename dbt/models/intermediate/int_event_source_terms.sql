{{ config(materialized='table') }}

-- Grain: one word or two-word phrase, per source, per event. Every term, with counts only.
--
-- The lists of posts behind each term are deliberately not built here. Most terms fail the
-- filters in event_group_terms, and carrying a list for each of them through the joins there
-- is what once filled 43 GB of temporary files.

select
    posts.event_hash,
    posts.group_hash,
    posts.source_hash,
    terms.term_hash,
    -- A post sits in one event once and a term sits in one text once, so rows are posts.
    count(*)              as posts_with_term,
    sum(terms.term_uses)  as term_uses

from {{ ref('int_event_posts_with_words') }} as posts
inner join {{ ref('int_post_terms') }} as terms
    on posts.post_text_id = terms.post_text_id
group by 1, 2, 3, 4
