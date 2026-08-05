-- The list of posts behind a term must contain exactly as many posts as the count shown
-- next to it.
--
-- This is the check that keeps the evidence honest. The dashboard prints "in 9 of this
-- group's 88 posts" and lets the reader click through to those posts; if the two are
-- computed differently they drift apart, and the reader is shown a different set of posts
-- from the one the number was based on. That already happened once, when the drill-down
-- matched the two words of a phrase anywhere in a post instead of next to each other, and
-- returned 18 posts for a count of 9.

select
    event_slug,
    media_group,
    term_type,
    term_label,
    posts_with_term,
    len(post_keys)  as posts_in_list

from {{ ref('event_group_terms') }}
where len(post_keys) != posts_with_term
