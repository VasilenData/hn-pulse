-- Stories by the UTC hour they were posted, and how well they did.
select
    cast(extract('hour' from posted_at) as integer) as posted_hour_utc,
    count(*)                                         as stories,
    round(avg(peak_score), 1)                        as avg_peak_score
from {{ ref('fct_stories') }}
group by 1
order by 1
