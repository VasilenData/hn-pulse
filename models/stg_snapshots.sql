-- One row per (snapshot, story). Types cast, domain parsed, exact duplicate snapshots removed.
with raw as (
    select * from read_csv_auto('data/raw_snapshots.csv', header = true)
),
typed as (
    select
        cast(snapshot_at as timestamp)  as snapshot_at,
        cast("rank" as integer)         as rank,
        cast(story_id as bigint)        as story_id,
        title,
        nullif(url, '')                 as url,
        author,
        cast(score as integer)          as score,
        cast(comments as integer)       as comments,
        cast(posted_at as timestamp)    as posted_at
    from raw
)
select
    *,
    coalesce(
        regexp_extract(url, '^https?://(?:www\.)?([^/:]+)', 1),
        'news.ycombinator.com'
    ) as domain
from typed
qualify row_number() over (partition by snapshot_at, story_id order by rank) = 1
