-- Every group's usual slice of coverage must add up to the whole, and the per-event slices
-- must too. If either drifts, every "more than usual" and "less than usual" label in the
-- cross-event comparison is measured against a baseline that does not exist.

with baseline_total as (

    select sum(distinct_baseline) as total
    from (
        select media_group, any_value(baseline_share_of_voice) as distinct_baseline
        from {{ ref('event_group_resonance') }}
        group by 1
    )

),

per_event_total as (

    select event_id, sum(share_of_voice) as total
    from {{ ref('event_group_resonance') }}
    group by 1

)

select 'baseline shares' as which, total from baseline_total where abs(total - 1.0) > 0.000001
union all
select 'event ' || event_id, total from per_event_total where abs(total - 1.0) > 0.000001
