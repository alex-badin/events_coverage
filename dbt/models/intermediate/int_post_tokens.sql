{{ config(materialized='table') }}

-- Grain: one word of one distinct post text, in the order it appears.
--
-- The raw material for comparing the vocabulary of different media groups. Splitting the
-- texts into words is done here, once, so that single words and two-word phrases are both
-- built from exactly the same word stream and cannot disagree.
--
-- One text is split once however many events matched it: neighbouring events share posts,
-- so there are about twice as many post-in-event rows as distinct posts. A table, because
-- splitting and stemming tens of millions of words on every read is what a view would do.
--
-- Position is kept because a phrase is two words that were next to each other; without the
-- position there is no way to know which words those were.

with texts as (

    select distinct post_text
    from {{ ref('event_message_detail') }}
    where post_text is not null

),

posts as (

    select
        hash(post_text)  as post_text_id,
        -- Lowercased so that "Курск" and "курск" are the same word. The split is on
        -- anything that is not a letter or digit, which also drops punctuation, emoji and
        -- the formatting marks Telegram posts are full of.
        regexp_split_to_array(lower(post_text), '[^a-zа-яё0-9]+')  as words
    from texts

),

numbered as (

    select
        posts.post_text_id,
        position.i                     as word_position,
        posts.words[position.i]        as word
    from posts,
         -- One row per word. len() is the number of words in the post.
         unnest(generate_series(1, len(posts.words))) as position(i)

),

stopwords as (

    select distinct term from {{ ref('russian_stopwords') }}

),

source_names as (

    select distinct source_name from {{ ref('stg_media_groups') }}

)

select
    numbered.post_text_id,
    numbered.word_position,
    numbered.word,

    -- Flagged rather than filtered out. Single-word counting drops these, but phrase
    -- building needs to know where they were: "в центре суджи" is only recognisable as a
    -- phrase if the stream still knows "в" sat there.
    stopwords.term is not null           as is_stopword,

    -- Numbers on their own carry no meaning for this comparison.
    regexp_full_match(numbered.word, '[0-9]+')  as is_number,

    -- Channels sign their posts, so a word that is the name of a source says nothing.
    source_names.source_name is not null  as is_source_name

from numbered
left join stopwords on numbered.word = stopwords.term
left join source_names on numbered.word = source_names.source_name
where numbered.word is not null
  and length(numbered.word) >= 2
