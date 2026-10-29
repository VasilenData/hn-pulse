select
    rank, story_id, title, domain, score, comments, author, snapshot_at
from {{ ref('stg_snapshots') }}
where snapshot_at = (select max(snapshot_at) from {{ ref('stg_snapshots') }})
order by rank
limit 30
