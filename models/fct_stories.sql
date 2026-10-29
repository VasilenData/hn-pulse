-- One row per story: peak performance and how long it stayed on the front-page window.
select
    story_id,
    any_value(title)                      as title,
    any_value(domain)                     as domain,
    any_value(author)                     as author,
    min(posted_at)                        as posted_at,
    min(snapshot_at)                      as first_seen_at,
    max(snapshot_at)                      as last_seen_at,
    count(*)                              as snapshots_seen,
    min(rank)                             as best_rank,
    max(score)                            as peak_score,
    max(comments)                         as peak_comments
from {{ ref('stg_snapshots') }}
group by story_id
