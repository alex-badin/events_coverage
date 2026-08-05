-- Grain: one event.
--
-- Public attention against media coverage. The question this answers is the one the
-- two source datasets can answer together and neither can answer alone: which events
-- were on people's minds but thin in the media, and which got heavy coverage without
-- being widely noticed.
--
-- Comparing a survey percentage with a post count directly would be meaningless — they
-- are different units. So both are turned into a position within the set of events
-- loaded here, and the gap is the distance between the two positions.
--
-- Read with care while the event set is small: with only a handful of events, a
-- position is a rough ordering, not a stable score. It becomes meaningful as more
-- events are added.

with overview as (

    select * from {{ ref('event_overview') }}

),

ranked as (

    select
        event_id,
        event_slug,
        event_name,
        fom_year,
        fom_week,
        match_start,

        attention_percentage,
        matched_posts,
        matched_posts_per_1000_published,
        sources_covering,
        sources_active,
        groups_covering,
        groups_active,

        count(*) over ()  as events_ranked,

        -- percent_rank puts the lowest value at 0 and the highest at 1.
        percent_rank() over (order by attention_percentage)              as attention_position,
        percent_rank() over (order by matched_posts)                     as volume_position,
        percent_rank() over (order by matched_posts_per_1000_published)  as intensity_position

    from overview
    where attention_percentage is not null
      and matched_posts is not null

)

select
    event_id,
    event_slug,
    event_name,
    fom_year,
    fom_week,
    match_start,

    attention_percentage,
    matched_posts,
    matched_posts_per_1000_published,
    sources_covering,
    sources_active,
    groups_covering,
    groups_active,
    events_ranked,

    attention_position,
    volume_position,
    intensity_position,

    -- Positive: the public named this event more often than the media volume would
    -- suggest. Negative: the media covered it more heavily than the public noticed.
    attention_position - volume_position   as attention_minus_volume,

    case
        when attention_position - volume_position >  0.25 then 'noticed more than covered'
        when attention_position - volume_position < -0.25 then 'covered more than noticed'
        else 'attention and coverage in line'
    end                                    as gap_direction

from ranked
