{{ config(materialized='table') }}

-- Grain: one word or two-word phrase in one distinct post text.
--
-- Counting a term once per text here is what lets the next step count posts by adding rows,
-- rather than keeping a set of post ids for every term.

select
    post_text_id,
    term_hash,
    sum(term_uses)  as term_uses

from {{ ref('int_post_term_forms') }}
group by 1, 2
