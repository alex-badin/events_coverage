-- Grain: one word or two-word phrase, per media group, per event.
--
-- Answers "which words did this group use that the others did not", which is not the same
-- question as "which words did this group use most". The most frequent words are the same
-- for everyone — they are the name of the event. What separates groups is the vocabulary
-- one of them reaches for and the rest do not.
--
-- The measure is a comparison, not a count: the share of *this* group's posts containing
-- the word, against the share of *everyone else's* posts in the same event. Posts are
-- counted, not word uses — otherwise one long post repeating a word twenty times would
-- look like a group-wide habit.
--
-- Three filters exist because the first version of this model returned almost nothing but
-- channel furniture — "прислать новость", "rybar поддержать", "whatsapp youtube рассылка",
-- and channel handles. Each filter targets one way that furniture gets in:
--
--   1. A word that is the name of a source is dropped. Channels sign their posts.
--   2. A term must be used by at least two channels in the group, and — where the group has
--      three or more channels covering the event — no single channel may account for more
--      than 70% of the posts carrying it. Two channels is not enough on its own, because
--      reposting spreads one channel's footer to its neighbours: Rybar's map block reaches
--      three war channels but 11 of its 13 posts are Rybar's own. A word that characterises
--      a group has to be used across the group.
--   3. A term must be more common in this event than in the same group's coverage of the
--      other events matched by the same method. Subscription pitches and sign-offs appear at the same rate whatever
--      the story is, so they fail this test; words the event itself brought in pass it.
--
-- One kind of furniture survives all three and is handled in the stopword list instead:
-- promotional blocks that a channel attaches to only some of its posts. Rybar's map footer
-- ("Онлайн-карты доступны по подписке … #Курск #Россия") is on 11 of its 23 Kursk posts, so
-- no share-based rule can remove it without also removing real words used at that rate — a
-- rule keyed on "every using channel puts it on 80% of its posts" was tried and removed
-- again, because it matched nothing while its near-misses were words like "зеленский" and
-- "курской". The words for subscribing, donating and feedback bots are listed in
-- seeds/russian_stopwords.csv under the "channel boilerplate" reason. That list only ever
-- names words about running a channel, never words about the events themselves.
--
-- This is word counting, not framing analysis. It reports which words appear where and
-- makes no claim about tone or intent. Every term keeps the post counts behind it, and the
-- posts stay one click away in the dashboard so any word can be read back in context.
--
-- The counting and the filters are in int_event_group_term_scores; this model adds the words and
-- the lists of posts to what survives.

with kept as (

    select * from {{ ref('int_event_group_term_scores') }}

),

term_labels as (

    select * from {{ ref('int_event_group_term_labels') }}

),

event_groups as (

    select distinct event_hash, group_hash, event_id, event_slug, media_group, media_group_key
    from {{ ref('int_event_posts_with_words') }}

),

kept_term_posts as (

    select * from {{ ref('int_event_group_term_posts') }}

),

post_lists as (

    select
        event_hash,
        group_hash,
        term_hash,
        -- The exact posts this term was counted in, so the dashboard's "read the posts
        -- behind this word" cannot disagree with the count beside it.
        list(source_name || ':' || message_id)  as post_keys

    from kept_term_posts
    group by 1, 2, 3

)

select
    event_groups.event_id,
    event_groups.event_slug,
    event_groups.media_group,
    event_groups.media_group_key,
    term_labels.term_type,
    term_labels.term_key,
    term_labels.term_label,

    kept.posts_with_term,
    kept.sources_with_term,
    kept.group_sources,
    kept.term_uses,
    kept.max_share_within_one_source,
    kept.top_source_share_of_term,
    post_lists.post_keys,
    kept.group_posts,
    kept.other_posts_with_term,
    kept.other_posts,

    kept.share_in_group,
    kept.share_elsewhere,
    kept.share_in_group_other_events,

    kept.distinctiveness,
    kept.event_specificity,

    row_number() over (
        partition by kept.event_hash, kept.group_hash, term_labels.term_type
        order by kept.distinctiveness desc, kept.posts_with_term desc, term_labels.term_key
    )  as distinctiveness_rank

from kept
inner join event_groups
    on  kept.event_hash = event_groups.event_hash
    and kept.group_hash = event_groups.group_hash
inner join term_labels
    on  kept.event_hash = term_labels.event_hash
    and kept.group_hash = term_labels.group_hash
    and kept.term_hash  = term_labels.term_hash
inner join post_lists
    on  kept.event_hash = post_lists.event_hash
    and kept.group_hash = post_lists.group_hash
    and kept.term_hash  = post_lists.term_hash
