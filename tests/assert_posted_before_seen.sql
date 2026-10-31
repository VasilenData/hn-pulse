-- A story cannot be posted after we saw it. A 10-minute tolerance absorbs clock differences.
select snapshot_at, story_id, posted_at
from {{ ref('stg_snapshots') }}
where posted_at > snapshot_at + interval 10 minute
