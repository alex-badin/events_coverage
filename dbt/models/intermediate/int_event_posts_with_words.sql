{{ config(materialized='table') }}

-- Grain: one matched post in one event, for posts with at least one countable word.
--
-- The denominator for every share in event_group_terms. A post made only of emoji, or only
-- of a channel's own name, has no words to compare and does not count.

with texts_with_words as (

    select distinct post_text_id
    from {{ ref('int_post_tokens') }}
    where not is_source_name

)

select
    detail.event_id,
    detail.event_slug,
    detail.media_group,
    detail.media_group_key,
    detail.source_name,
    detail.message_id,
    hash(detail.post_text)  as post_text_id,

    -- Numbers standing for the event, group and source, for the counting downstream.
    hash(detail.event_id)     as event_hash,
    hash(detail.media_group)  as group_hash,
    hash(detail.source_name)  as source_hash

from {{ ref('event_message_detail') }} as detail
inner join texts_with_words
    on hash(detail.post_text) = texts_with_words.post_text_id
