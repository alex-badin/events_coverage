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
--      other events. Subscription pitches and sign-offs appear at the same rate whatever
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

{% set smoothing = 0.02 %}
{% set min_posts_with_term = 3 %}
{% set min_group_posts = 10 %}
{% set min_event_specificity = 0.4 %}
{% set max_top_source_share = 0.7 %}

with tokens as (

    select * from {{ ref('int_event_tokens') }}

),

source_names as (

    select distinct source_name from {{ ref('stg_media_groups') }}

),

-- Words that are simply the name of a channel. Dropped before anything is counted.
usable_tokens as (

    select tokens.*
    from tokens
    left join source_names on tokens.word = source_names.source_name
    where source_names.source_name is null

),

-- How many posts each group contributed to each event, and how many sources those came
-- from. The denominator for every share below.
group_post_counts as (

    select
        event_id,
        media_group,
        count(distinct message_id)   as group_posts,
        count(distinct source_name)  as group_sources

    from usable_tokens
    group by 1, 2

),

-- Single words, counted per source first. The per-source level is kept because filter 4
-- needs to know what share of an individual channel's posts a term sits on.
word_terms_by_source as (

    select
        event_id,
        event_slug,
        media_group,
        media_group_key,
        source_name,
        'word'                          as term_type,
        word_stem                       as term_key,
        mode(word)                      as term_label,
        count(distinct message_id)      as posts_with_term,
        count(*)                        as term_uses,
        -- The exact posts this term was counted in. Carried through so the dashboard's
        -- "read the posts behind this word" cannot disagree with the count beside it.
        list(distinct source_name || ':' || message_id)  as post_keys

    from usable_tokens
    where not is_stopword
      and not is_number
      and length(word) >= 4
    group by 1, 2, 3, 4, 5, 6, 7

),

-- Two words that stood next to each other in the same post. Built from the same word
-- stream, so a phrase is never made of words that were not actually adjacent. Neither half
-- may be a stopword, which keeps "курской области" and drops "в центре".
phrase_pairs as (

    select
        first_word.event_id,
        first_word.event_slug,
        first_word.media_group,
        first_word.media_group_key,
        first_word.source_name,
        first_word.message_id,
        first_word.word_stem || ' ' || second_word.word_stem  as term_key,
        first_word.word || ' ' || second_word.word            as term_label

    from usable_tokens as first_word
    inner join usable_tokens as second_word
        on  first_word.event_id       = second_word.event_id
        and first_word.source_name    = second_word.source_name
        and first_word.message_id     = second_word.message_id
        and second_word.word_position = first_word.word_position + 1

    where not first_word.is_stopword  and not first_word.is_number
      and not second_word.is_stopword and not second_word.is_number
      and length(first_word.word)  >= 3
      and length(second_word.word) >= 3

),

phrase_terms_by_source as (

    select
        event_id,
        event_slug,
        media_group,
        media_group_key,
        source_name,
        'phrase'                        as term_type,
        term_key,
        mode(term_label)                as term_label,
        count(distinct message_id)      as posts_with_term,
        count(*)                        as term_uses,
        list(distinct source_name || ':' || message_id)  as post_keys

    from phrase_pairs
    group by 1, 2, 3, 4, 5, 6, 7

),

terms_by_source as (

    select * from word_terms_by_source
    union all
    select * from phrase_terms_by_source

),

-- How many posts each individual channel contributed to each event.
source_post_counts as (

    select
        event_id,
        source_name,
        count(distinct message_id)  as source_posts

    from usable_tokens
    group by 1, 2

),

-- Roll the per-source counts up to the group. The largest share the term takes of any one
-- channel's posts is kept as a diagnostic: it is how you check, from the table alone,
-- whether a surprising term is a group habit or one channel's tic.
all_terms as (

    select
        terms_by_source.event_id,
        terms_by_source.event_slug,
        terms_by_source.media_group,
        terms_by_source.media_group_key,
        terms_by_source.term_type,
        terms_by_source.term_key,

        -- The spelling used in most posts, so the dashboard shows a real word and not the
        -- shortened form the counting is done on.
        arg_max(terms_by_source.term_label, terms_by_source.posts_with_term)  as term_label,

        sum(terms_by_source.posts_with_term)   as posts_with_term,
        count(distinct terms_by_source.source_name) as sources_with_term,
        sum(terms_by_source.term_uses)         as term_uses,
        flatten(list(terms_by_source.post_keys))  as post_keys,

        max(
            terms_by_source.posts_with_term::double / source_post_counts.source_posts
        )  as max_share_within_one_source,

        -- What share of the posts carrying this term came from its single busiest channel.
        -- Near 1 means one channel is doing all the talking and the rest are reposting it.
        max(terms_by_source.posts_with_term)::double
            / nullif(sum(terms_by_source.posts_with_term), 0)  as top_source_share_of_term

    from terms_by_source
    inner join source_post_counts
        on  terms_by_source.event_id    = source_post_counts.event_id
        and terms_by_source.source_name = source_post_counts.source_name
    group by 1, 2, 3, 4, 5, 6

),

-- The same term across the whole event, so each group can be compared with everyone else.
event_term_totals as (

    select
        event_id,
        term_type,
        term_key,
        sum(posts_with_term)  as event_posts_with_term

    from all_terms
    group by 1, 2, 3

),

-- The same term across everything the same group said about the *other* events. This is
-- what tells a word the event brought in apart from a word the group always uses.
group_term_totals as (

    select
        media_group,
        term_type,
        term_key,
        sum(posts_with_term)  as group_posts_with_term_all_events

    from all_terms
    group by 1, 2, 3

),

group_totals as (

    select
        media_group,
        sum(group_posts)  as group_posts_all_events

    from group_post_counts
    group by 1

),

event_post_counts as (

    select event_id, sum(group_posts) as event_posts
    from group_post_counts
    group by 1

),

compared as (

    select
        all_terms.event_id,
        all_terms.event_slug,
        all_terms.media_group,
        all_terms.media_group_key,
        all_terms.term_type,
        all_terms.term_key,
        all_terms.term_label,
        all_terms.posts_with_term,
        all_terms.sources_with_term,
        all_terms.term_uses,
        all_terms.max_share_within_one_source,
        all_terms.top_source_share_of_term,
        all_terms.post_keys,

        group_post_counts.group_posts,
        group_post_counts.group_sources,

        event_term_totals.event_posts_with_term - all_terms.posts_with_term  as other_posts_with_term,
        event_post_counts.event_posts - group_post_counts.group_posts        as other_posts,

        all_terms.posts_with_term::double / group_post_counts.group_posts    as share_in_group,

        -- Everyone else, same event.
        case
            when event_post_counts.event_posts - group_post_counts.group_posts > 0
            then (event_term_totals.event_posts_with_term - all_terms.posts_with_term)::double
                 / (event_post_counts.event_posts - group_post_counts.group_posts)
        end  as share_elsewhere,

        -- Same group, the other events.
        case
            when group_totals.group_posts_all_events - group_post_counts.group_posts > 0
            then (group_term_totals.group_posts_with_term_all_events - all_terms.posts_with_term)::double
                 / (group_totals.group_posts_all_events - group_post_counts.group_posts)
        end  as share_in_group_other_events

    from all_terms
    inner join group_post_counts
        on  all_terms.event_id    = group_post_counts.event_id
        and all_terms.media_group = group_post_counts.media_group
    inner join event_term_totals
        on  all_terms.event_id  = event_term_totals.event_id
        and all_terms.term_type = event_term_totals.term_type
        and all_terms.term_key  = event_term_totals.term_key
    inner join group_term_totals
        on  all_terms.media_group = group_term_totals.media_group
        and all_terms.term_type   = group_term_totals.term_type
        and all_terms.term_key    = group_term_totals.term_key
    inner join group_totals
        on all_terms.media_group = group_totals.media_group
    inner join event_post_counts
        on all_terms.event_id = event_post_counts.event_id

    where all_terms.posts_with_term     >= {{ min_posts_with_term }}
      and group_post_counts.group_posts >= {{ min_group_posts }}
      -- Used by more than one channel in the group, unless the group only has one channel
      -- covering the event at all.
      and all_terms.sources_with_term   >= least(2, group_post_counts.group_sources)
      -- Not one channel's boilerplate carried into its neighbours by reposting. Only
      -- applied where the group has enough channels for the share to mean anything.
      and (
            group_post_counts.group_sources < 3
            or all_terms.top_source_share_of_term <= {{ max_top_source_share }}
          )

),

scored as (

    select
        *,

        -- How much more often this group's posts carry the term than everyone else's, on a
        -- doubling scale: 1 means twice as often, 2 means four times, -1 means half as
        -- often. Both shares get {{ smoothing }} added first, so a term in three posts and
        -- nowhere else scores high but not infinitely high.
        log2(
            (share_in_group + {{ smoothing }})
            / (coalesce(share_elsewhere, 0) + {{ smoothing }})
        )  as distinctiveness,

        -- The same scale, comparing this event with the group's coverage of the others.
        -- Channel furniture sits near zero here because it appears everywhere equally.
        log2(
            (share_in_group + {{ smoothing }})
            / (coalesce(share_in_group_other_events, 0) + {{ smoothing }})
        )  as event_specificity

    from compared

)

select
    event_id,
    event_slug,
    media_group,
    media_group_key,
    term_type,
    term_key,
    term_label,

    posts_with_term,
    sources_with_term,
    term_uses,
    max_share_within_one_source,
    top_source_share_of_term,
    post_keys,
    group_posts,
    other_posts_with_term,
    other_posts,

    share_in_group,
    share_elsewhere,
    share_in_group_other_events,

    distinctiveness,
    event_specificity,

    row_number() over (
        partition by event_id, media_group, term_type
        order by distinctiveness desc, posts_with_term desc, term_key
    )  as distinctiveness_rank

from scored
-- The term has to be one this event brought in, not one the group always uses.
where event_specificity >= {{ min_event_specificity }}
