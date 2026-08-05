-- How much each source published on each calendar day, across the whole corpus.
--
-- This is the denominator model. Without it, "this group did not cover the event"
-- and "this group was not in the data yet" look identical in the numbers.

with source as (

    select * from {{ source('raw', 'source_day_activity') }}

)

select
    source          as source_name,
    activity_date,
    post_count

from source
where activity_date is not null
