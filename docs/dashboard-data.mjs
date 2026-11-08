// Validate every field the dashboard reads before replacing the last good export.
// Timestamp validity is reported separately by the freshness assessment.
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const count = value => Number.isSafeInteger(value) && value >= 0;
const metric = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const text = value => typeof value === 'string';

export function validateDashboardData(data) {
  const marts = {
    mart_daily_summary: row => count(row.snapshots),
    mart_front_page_now: row => count(row.rank) && row.rank > 0 && metric(row.score)
      && count(row.comments) && (row.title === null || text(row.title)) && text(row.domain),
    mart_top_domains: row => text(row.domain) && count(row.stories),
    mart_hourly_activity: row => count(row.posted_hour_utc) && row.posted_hour_utc < 24 && metric(row.avg_peak_score),
  };
  if (!record(data) || !text(data.generated_at)
      || !Object.entries(marts).every(([key, valid]) => Array.isArray(data[key])
        && data[key].every(row => record(row) && valid(row)))) {
    throw new Error('The dashboard export has invalid data');
  }
  const q = data.quality;
  if (q !== null && q !== undefined && (!record(q) || !record(q.tests) || !record(q.rows)
      || !['pass', 'warn', 'fail', 'error'].every(key => count(q.tests[key]))
      || !count(q.contracts_enforced) || !count(q.models_total)
      || q.contracts_enforced > q.models_total
      || !count(q.rows.fct_stories) || !count(q.rows.stg_snapshots))) {
    throw new Error('The dashboard export has an invalid health report');
  }
  return data;
}

export async function fetchDashboardData(fetcher = fetch) {
  const response = await fetcher('data.json', {cache: 'no-store', signal: AbortSignal.timeout(15_000)});
  if (!response.ok) throw new Error('Export unavailable');
  return validateDashboardData(await response.json());
}
