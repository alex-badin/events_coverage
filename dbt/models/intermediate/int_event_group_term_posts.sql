{{ config(materialized='table') }}

-- Grain: one post carrying one term, for the terms that survived int_event_group_term_scores.
--
-- These rows are the posts the counts were added up from, so a list of posts built from them
-- cannot disagree with the count beside it. A table, because building the lists and the labels
-- in one query with this join ran out of memory at a 6 GB limit, while each step alone fits.

select
    posts.event_hash,
    posts.group_hash,
    posts.source_hash,
    posts.source_name,
    posts.message_id,
    posts.post_text_id,
    terms.term_hash

from {{ ref('int_event_posts_with_words') }} as posts
inner join {{ ref('int_post_terms') }} as terms
    on posts.post_text_id = terms.post_text_id
inner join {{ ref('int_event_group_term_scores') }} as kept
    on  posts.event_hash = kept.event_hash
    and posts.group_hash = kept.group_hash
    and terms.term_hash  = kept.term_hash
