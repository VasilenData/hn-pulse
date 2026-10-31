-- A partial API response would silently shrink the dashboard. We request 100 stories and
-- normally keep about 99 (a few items are dead or deleted), so fewer than 90 means a bad run.
select snapshot_at, count(*) as stories
from {{ ref('stg_snapshots') }}
group by snapshot_at
having count(*) < 90
