-- The "everything" scope must hold every matched post exactly once: as many posts as there
-- are distinct (source, message) pairs among all matched posts, however many events a post
-- was matched to. Returns a row only when the two counts differ.

-- The test reads several models, so Dagster needs to be told which one to attach it to.
{{ config(meta={'dagster': {'ref': {'name': 'theme_group_coverage'}}}) }}

with rolled_up as (

    select sum(distinct_matched_posts) as posts
    from {{ ref('theme_group_coverage') }}
    where scope_type = 'all'

),

distinct_posts as (

    select count(distinct concat_ws(':', source_name, message_id)) as posts
    from {{ ref('event_message_detail') }}

)

select rolled_up.posts as rolled_up_posts, distinct_posts.posts as distinct_posts
from rolled_up, distinct_posts
where rolled_up.posts <> distinct_posts.posts
