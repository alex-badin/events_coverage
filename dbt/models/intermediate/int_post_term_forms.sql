{{ config(materialized='table') }}

-- Grain: one spelling of one word or two-word phrase in one distinct post text.
--
-- Plain counts on purpose. A list of spellings per term would be shorter to write, but list
-- aggregates this size ran out of memory at a 6 GB limit where plain counts spill to disk.

with usable_tokens as (

    select
        tokens.*,
        -- The dictionary form, so «войны» and «войну» count as «война». A word the dictionary
        -- step skipped (shorter than three letters) keeps its spelling.
        coalesce(lemmas.lemma, tokens.word)  as word_lemma

    from {{ ref('int_post_tokens') }} as tokens
    left join {{ ref('int_word_lemmas') }} as lemmas
        on tokens.word = lemmas.word
    where not tokens.is_source_name

),

words as (

    select
        post_text_id,
        'word'        as term_type,
        word_lemma    as term_key,
        word          as term_form,
        count(*)      as term_uses

    from usable_tokens
    where not is_stopword
      and not is_number
      and length(word) >= 4
    group by 1, 2, 3, 4

),

-- Two words that stood next to each other in the same post. Built from the same word
-- stream, so a phrase is never made of words that were not actually adjacent. Neither half
-- may be a stopword, which keeps "курской области" and drops "в центре".
phrase_tokens as (

    select post_text_id, word_position, word, word_lemma
    from usable_tokens
    where not is_stopword
      and not is_number
      and length(word) >= 3

),

phrases as (

    select
        first_word.post_text_id,
        'phrase'  as term_type,
        first_word.word_lemma || ' ' || second_word.word_lemma  as term_key,
        first_word.word || ' ' || second_word.word            as term_form,
        count(*)  as term_uses

    from phrase_tokens as first_word
    inner join phrase_tokens as second_word
        on  first_word.post_text_id   = second_word.post_text_id
        and second_word.word_position = first_word.word_position + 1
    group by 1, 2, 3, 4

)

select
    post_text_id,
    -- A number standing for the term, used for all the counting downstream. Grouping 44 million
    -- rows on it needed no temporary files; the same grouping on the text took 3 GB of them.
    hash(term_type, term_key)  as term_hash,
    term_type,
    term_key,
    term_form,
    term_uses

from (
    select * from words
    union all
    select * from phrases
)
