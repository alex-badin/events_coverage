-- Each theme must appear at most once per survey week, and each scope at most once per
-- media group. A second row would mean a join fanned out and the heatmap or the totals
-- row on the dashboard would add the same mentions or posts twice.
--
-- A test passes when it returns no rows.

-- The test reads several models, so Dagster needs to be told which one to attach it to.
{{ config(meta={'dagster': {'ref': {'name': 'theme_week_attention'}}}) }}

select 'theme_week_attention' as model, theme_id as scope_id, week_start::varchar as part, count(*) as rows_found
from {{ ref('theme_week_attention') }}
group by 1, 2, 3
having count(*) > 1

union all

select 'theme_group_coverage', scope_type || ':' || scope_id, media_group, count(*)
from {{ ref('theme_group_coverage') }}
group by 1, 2, 3
having count(*) > 1
