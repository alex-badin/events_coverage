-- A group cannot have covered an event with more posts than it published in total, and
-- cannot have more covering sources than active ones. If either happens, the coverage
-- counts and the denominator they are divided by are not describing the same window,
-- and every "share of own output" figure is wrong.

select
    event_id,
    media_group,
    matched_posts,
    posts_published_in_window,
    sources_covering,
    sources_active

from {{ ref('event_group_coverage') }}
where matched_posts > posts_published_in_window
   or sources_covering > sources_active
