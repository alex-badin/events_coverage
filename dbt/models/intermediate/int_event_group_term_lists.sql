{{ config(materialized='table') }}

-- Grain: one word or two-word phrase, per media group, per event, for the surviving terms.
--
-- The exact posts each term was counted in, so the dashboard's "read the posts behind this word"
-- cannot disagree with the count beside it. Its own table because the same lists built inside
-- event_group_terms, next to that model's joins, filled the 30 GB cap on temporary files once
-- the warehouse held 863 events; alone they need none.
--
-- It runs after the labels, never beside them: both spill to disk, and side by side they filled the
-- 30 GB cap that each stays far below alone.
-- depends_on: {{ ref('int_event_group_term_labels') }}

select
    event_hash,
    group_hash,
    term_hash,
    list(source_name || ':' || message_id)  as post_keys

from {{ ref('int_event_group_term_posts') }}
group by 1, 2, 3
