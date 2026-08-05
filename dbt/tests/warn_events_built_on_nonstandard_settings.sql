-- Warn about events whose matched set cannot be compared with the others, and say which
-- of the two possible reasons applies.
--
-- Reason one — a different relevance bar. The standard is to keep anything scoring 0.35
-- or higher on Cohere rerank-v3.5. A lower cut-off admits weaker matches, so the post
-- count is inflated relative to events built at 0.35.
--
-- Reason two — an incomplete search. Only posts that have an embedding vector can be
-- found. The current Qwen3 vectors cover the whole corpus, but the older archived Cohere
-- vectors covered only part of it, so an event retrieved that way may have had a large
-- share of its window invisible to the search. Its counts are then an undercount.
--
-- This warns rather than fails. These are real pilot datasets; whether to rebuild them or
-- drop them is a decision about scope, not an error SQL can fix. The build stays green
-- and the run names the events that need attention.

{{ config(severity = 'warn') }}

select
    event_slug,
    retriever,
    rerank_threshold,
    matched_posts,
    searchable_posts_in_window,
    posts_published_in_window,
    round(searchable_share_of_window, 3)  as searchable_share_of_window,

    case
        when not standard_relevance_cutoff and searchable_share_of_window < 0.9
            then 'lower relevance cut-off AND an incomplete search of the window'
        when not standard_relevance_cutoff
            then 'lower relevance cut-off than the other events'
        else 'incomplete search: part of the window had no embedding vectors'
    end                                   as reason

from {{ ref('event_overview') }}
where not standard_relevance_cutoff
   or searchable_share_of_window < 0.9
