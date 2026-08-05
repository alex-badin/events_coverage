-- One row per news post matched to an event.
--
-- Staging work only: rename, retype, and attach the event key. No filtering and no
-- aggregation, so the row count here equals the number of matched posts loaded.

with source as (

    select * from {{ source('raw', 'event_matches') }}

),

renamed as (

    select
        -- Same fingerprint as stg_events, so the two models join on one key. The
        -- relationships test in _staging.yml is what proves they really line up.
        md5(concat_ws('|', fom_year::varchar, fom_week::varchar, event_name))  as event_id,

        event_slug,
        source                                        as source_name,
        message_id,

        -- The stored value carries a UTC offset. Converting it to a plain UTC
        -- timestamp once, here, means no later model can silently reinterpret it in
        -- whatever timezone the machine running dbt happens to be set to.
        (date at time zone 'UTC')                     as published_at,
        (date at time zone 'UTC')::date               as published_date,

        is_digest = 1                                 as is_digest,

        summary,
        original_message,

        -- Missing is not the same as zero. The view counter is filled on every matched
        -- post; the forward counter is missing on some, so it stays null and every
        -- later sum ignores it rather than counting it as no forwards.
        views                                         as views,
        forwards                                      as forwards,

        cosine_max,
        rerank_score,
        keyword_match

    from source

)

select * from renamed
