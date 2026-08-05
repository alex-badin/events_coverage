-- Grain: one word of one matched post, in the order it appears.
--
-- The raw material for comparing the vocabulary of different media groups. Splitting the
-- posts into words is done here, once, so that single words and two-word phrases are both
-- built from exactly the same word stream and cannot disagree.
--
-- Position is kept because a phrase is two words that were next to each other; without the
-- position there is no way to know which words those were.

with posts as (

    select
        event_id,
        event_slug,
        media_group,
        media_group_key,
        source_name,
        message_id,
        -- Lowercased so that "Курск" and "курск" are the same word. The split is on
        -- anything that is not a letter or digit, which also drops punctuation, emoji and
        -- the formatting marks Telegram posts are full of.
        regexp_split_to_array(lower(post_text), '[^a-zа-яё0-9]+')  as words
    from {{ ref('event_message_detail') }}
    where post_text is not null

),

numbered as (

    select
        posts.event_id,
        posts.event_slug,
        posts.media_group,
        posts.media_group_key,
        posts.source_name,
        posts.message_id,
        position.i                     as word_position,
        posts.words[position.i]        as word
    from posts,
         -- One row per word. len() is the number of words in the post.
         unnest(generate_series(1, len(posts.words))) as position(i)

),

stopwords as (

    select distinct term from {{ ref('russian_stopwords') }}

)

select
    numbered.event_id,
    numbered.event_slug,
    numbered.media_group,
    numbered.media_group_key,
    numbered.source_name,
    numbered.message_id,
    numbered.word_position,
    numbered.word,

    -- The word with its grammatical ending cut off, so different forms count together.
    {{ russian_stem('numbered.word') }}  as word_stem,

    -- Flagged rather than filtered out. Single-word counting drops these, but phrase
    -- building needs to know where they were: "в центре суджи" is only recognisable as a
    -- phrase if the stream still knows "в" sat there.
    stopwords.term is not null           as is_stopword,

    -- Numbers on their own carry no meaning for this comparison.
    regexp_full_match(numbered.word, '[0-9]+')  as is_number

from numbered
left join stopwords on numbered.word = stopwords.term
where numbered.word is not null
  and length(numbered.word) >= 2
