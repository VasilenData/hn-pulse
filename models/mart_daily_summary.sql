select
    cast(snapshot_at as date)             as day,
    count(distinct snapshot_at)           as snapshots,
    count(distinct story_id)              as distinct_stories,
    round(avg(score), 1)                  as avg_score,
    round(avg(comments), 1)               as avg_comments
from {{ ref('stg_snapshots') }}
group by 1
order by 1
