-- One row per event that was searched on the current settings and kept no post.
--
-- Not a matched set — there are no posts — but a result all the same: the search ran,
-- and no candidate reached the relevance cut-off. week_events uses it to say "searched,
-- nothing passed the cut-off" instead of "not measured yet".

with source as (

    select * from {{ source('raw', 'empty_event_searches') }}

)

select
    -- Same fingerprint as stg_events, so the search joins to its survey row.
    md5(concat_ws('|', fom_year::varchar, fom_week::varchar, event_name))  as event_id,
    event_slug,
    event_name,
    fom_year,
    fom_week,
    built_at::timestamp     as built_at,
    retriever,
    rerank_model,
    rerank_threshold,
    candidates              as candidates_reranked,
    kept

from source
