-- The number of matched posts the dashboard shows must equal the number the matching
-- run itself recorded when it built the dataset, less the posts whose source is now
-- archived and therefore out of scope.
--
-- This is the check that catches a lost or duplicated row anywhere between the source
-- file and the mart: the manifest count comes from the Python pipeline, the mart count
-- from the SQL, and they are computed completely independently of each other.
--
-- The archived subtraction keeps that exact. Every loaded dataset was built before the
-- 2026-08-03 decision to leave 28 out-of-scope sources out of the study, so its manifest
-- count still includes their posts; the loader counts those posts per event and the
-- difference must land on the nose.

with reported as (

    select event_id, matched_posts_expected
    from {{ ref('stg_event_datasets') }}

),

computed as (

    select event_id, matched_posts
    from {{ ref('event_overview') }}

)

select
    reported.event_id,
    reported.matched_posts_expected,
    computed.matched_posts

from reported
full outer join computed on reported.event_id = computed.event_id
where reported.matched_posts_expected is distinct from computed.matched_posts
