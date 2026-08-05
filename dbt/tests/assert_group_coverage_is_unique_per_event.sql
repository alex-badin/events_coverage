-- Each media group must appear at most once per event. If it appears twice, a join has
-- fanned out and every count in the dashboard is inflated.
--
-- A test passes when it returns no rows.

select
    event_id,
    media_group,
    count(*)  as rows_found

from {{ ref('event_group_coverage') }}
group by 1, 2
having count(*) > 1
