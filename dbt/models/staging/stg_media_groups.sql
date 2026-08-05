-- One row per in-scope news source, with the media group it belongs to.
--
-- The grouping is hand-maintained (configs/media_groups.yaml). As of 2026-08-03 every
-- source in the news database is either in a group (56 sources) or in the `archived:`
-- list (28 sources, out of scope: regional outlets and channels that are not news media).
-- Archived sources are dropped by scripts/load_warehouse.py before they reach the
-- warehouse, so there is no "uncategorized" bucket to carry through the totals any more.
-- raw.archived_sources records what was excluded and why.

with source as (

    select * from {{ source('raw', 'media_groups') }}

)

select
    source        as source_name,
    group_key     as media_group_key,
    group_label   as media_group,
    is_grouped

from source
