select
    domain,
    count(*)                              as stories,
    round(avg(peak_score), 1)             as avg_peak_score,
    sum(peak_comments)                    as total_comments
from {{ ref('fct_stories') }}
where domain <> 'news.ycombinator.com'
group by domain
order by stories desc, avg_peak_score desc
limit 15
