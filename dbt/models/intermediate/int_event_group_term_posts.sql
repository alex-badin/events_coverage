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
-- One combined key, so that posts must be joined to terms before this join can run. Joining the
-- three keys separately let DuckDB pair each kept term with every text carrying it, in all events,
-- first, which took about 45 s in a full build instead of 4 s.
inner join {{ ref('int_event_group_term_scores') }} as kept
    on hash(posts.event_hash, posts.group_hash, terms.term_hash)
       = hash(kept.event_hash, kept.group_hash, kept.term_hash)
