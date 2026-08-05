-- Every group's share of an event's coverage must add up to the whole event. Allowing a
-- small rounding tolerance because these are fractions, not integers.

select
    event_id,
    sum(share_of_voice)  as total_share

from {{ ref('event_group_coverage') }}
group by 1
having abs(sum(share_of_voice) - 1.0) > 0.000001
