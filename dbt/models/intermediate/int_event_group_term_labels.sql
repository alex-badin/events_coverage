{{ config(materialized='table') }}

-- Grain: one word or two-word phrase, per media group, per event, for the surviving terms.
--
-- The spelling shown for each term. Its own table for the same reason as
-- int_event_group_term_posts: together with the lists of posts it does not fit in 6 GB.

with kept_term_posts as (

    select * from {{ ref('int_event_group_term_posts') }}

),

source_terms as (

    select * from {{ ref('int_event_source_terms') }}

),

-- How often each spelling of a term was used, per channel.
term_form_counts as (

    select
        kept_term_posts.event_hash,
        kept_term_posts.group_hash,
        kept_term_posts.source_hash,
        forms.term_hash,
        forms.term_type,
        forms.term_key,
        forms.term_form,
        sum(forms.term_uses)  as form_uses

    from kept_term_posts
    inner join {{ ref('int_post_term_forms') }} as forms
        on  kept_term_posts.post_text_id = forms.post_text_id
        and kept_term_posts.term_hash    = forms.term_hash
    group by 1, 2, 3, 4, 5, 6, 7

),

-- Each channel's most used spelling. A tie goes to the alphabetically first spelling, so two
-- builds of the same data show the same word.
source_labels as (

    select
        event_hash,
        group_hash,
        source_hash,
        term_hash,
        term_type,
        term_key,
        arg_min(term_form, (-form_uses, term_form))  as source_label

    from term_form_counts
    group by 1, 2, 3, 4, 5, 6

),

-- The spelling used by the channel with the most posts carrying the term, so the dashboard
-- shows a real word and not the shortened form the counting is done on.
term_labels as (

    select
        source_labels.event_hash,
        source_labels.group_hash,
        source_labels.term_hash,
        source_labels.term_type,
        source_labels.term_key,
        arg_min(
            source_labels.source_label,
            (-source_terms.posts_with_term, source_labels.source_label)
        )  as term_label

    from source_labels
    inner join source_terms
        on  source_labels.event_hash  = source_terms.event_hash
        and source_labels.group_hash  = source_terms.group_hash
        and source_labels.source_hash = source_terms.source_hash
        and source_labels.term_hash   = source_terms.term_hash
    group by 1, 2, 3, 4, 5

)

select * from term_labels
