-- A term presented as characteristic of a media group must actually be used across the
-- group, not be one channel's boilerplate that reposting spread to its neighbours.
--
-- This guards the rule the model relies on, because the whole table is misleading if it
-- breaks: a reader seeing "войска" listed under a group will take it as something that
-- group says, not as something one of its channels says and two others copied.

select
    event_slug,
    media_group,
    term_label,
    sources_with_term,
    top_source_share_of_term

from {{ ref('event_group_terms') }}
-- A group with one channel covering the event can only show that channel's terms (the
-- model allows it); everywhere else a term needs two channels.
where sources_with_term < least(2, group_sources)
   or (group_posts is not null and sources_with_term >= 3 and top_source_share_of_term > 0.7)
