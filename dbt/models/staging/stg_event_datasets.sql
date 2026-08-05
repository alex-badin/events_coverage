-- One row per event that has a matched post set, with the settings used to build it.
--
-- This is the provenance record: which retriever found the candidates, what relevance
-- threshold kept them, how many were considered. The dashboard shows these next to the
-- counts so a reader can see how a number was produced.

with source as (

    select * from {{ source('raw', 'event_datasets') }}

)

select
    md5(concat_ws('|', fom_year::varchar, fom_week::varchar, event_name))  as event_id,

    event_slug,
    event_name,
    fom_year,
    fom_week,

    -- Stored as text in the manifest file; the FOM attention share is a number.
    try_cast(fom_percentage as double)      as attention_percentage,
    fom_quotes,

    built_at::timestamp                     as built_at,
    match_start::date                       as match_start,
    match_end_exclusive::date               as match_end_exclusive,

    retriever,
    embed_model,
    rerank_model,
    top_k                                   as rerank_candidates_requested,
    rerank_threshold,
    candidates                              as candidates_reranked,
    kept                                    as matched_posts_reported,

    -- Posts the matching run kept but that are no longer in scope, because their source
    -- is in the `archived:` list of configs/media_groups.yaml (regional outlets and
    -- channels that are not news media, set aside on 2026-08-03). Every dataset here was
    -- built before that decision, so the reported count above still includes them.
    archived_posts_excluded,
    kept - archived_posts_excluded          as matched_posts_expected,

    -- Posts in the window that had an embedding vector, and so could be found at all.
    -- The current Qwen3 vectors cover every post; the older archived Cohere vectors
    -- covered only part of the corpus, which is why this number matters.
    embedded_pool                           as searchable_posts_in_window

from source
