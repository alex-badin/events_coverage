-- Grain: one matched post.
--
-- The bottom of the drill-down. A reader who does not believe a bar on the chart clicks
-- through to here and reads the posts the bar is made of, with the relevance score that
-- let each one in.

with messages as (

    select * from {{ ref('int_event_messages') }}

)

select
    event_id,
    event_slug,
    event_name,
    media_group,
    media_group_key,
    source_name,
    message_id,

    published_at,
    published_date,
    days_from_window_start,
    hours_from_window_start,

    is_digest,
    views,
    forwards,
    rerank_score,
    keyword_match,

    summary,

    -- War and military channels store the post as a Telegram record written out as
    -- JSON rather than as plain text. Where that is the case the readable text is
    -- pulled out, so the drill-down shows the post instead of a wall of field names.
    case
        when json_valid(original_message)
             and json_extract_string(original_message, '$._') = 'Message'
        then json_extract_string(original_message, '$.message')
        else original_message
    end  as post_text,

    length(
        case
            when json_valid(original_message)
                 and json_extract_string(original_message, '$._') = 'Message'
            then json_extract_string(original_message, '$.message')
            else original_message
        end
    )  as post_text_length

from messages
