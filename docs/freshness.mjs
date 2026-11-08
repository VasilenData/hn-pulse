// Public scheduling is defined in .github/workflows/pipeline.yml: every three hours.
// Allow one extra interval for delayed GitHub Actions runs before flagging an export.
export const EXPECTED_INTERVAL_HOURS = 3;
export const STALE_AFTER_HOURS = 6;
const HOUR_MS = 60 * 60 * 1000;
const CLOCK_SKEW_MS = 5 * 60 * 1000;

function timestampMs(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$/i.test(value)) return NaN;
  // Legacy mart exports use timezone-free DuckDB TIMESTAMP values, all stored in UTC.
  const hasZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
  return Date.parse(value.replace(' ', 'T') + (hasZone ? '' : 'Z'));
}

function newestSnapshotMs(data) {
  if (data?.quality?.newest_snapshot_at !== undefined) return timestampMs(data.quality.newest_snapshot_at);
  // Keep the page compatible with an older JSON export during deployment.
  const times = (data?.mart_front_page_now ?? []).map(row => timestampMs(row.snapshot_at)).filter(Number.isFinite);
  return times.length ? Math.max(...times) : NaN;
}

export function assessFreshness(data, now = Date.now()) {
  const snapshot = newestSnapshotMs(data);
  const publication = timestampMs(data?.generated_at);
  if (![now, snapshot, publication].every(Number.isFinite)) {
    return {state: 'unknown', snapshotAgeHours: null, publicationAgeHours: null};
  }
  if (snapshot - now > CLOCK_SKEW_MS || publication - now > CLOCK_SKEW_MS) {
    return {state: 'clock-skew', snapshotAgeHours: null, publicationAgeHours: null};
  }
  const snapshotAgeHours = Math.max(0, (now - snapshot) / HOUR_MS);
  const publicationAgeHours = Math.max(0, (now - publication) / HOUR_MS);
  return {
    state: Math.max(snapshotAgeHours, publicationAgeHours) >= STALE_AFTER_HOURS ? 'stale' : 'fresh',
    snapshotAgeHours,
    publicationAgeHours,
  };
}

export function formatAge(hours) {
  if (!Number.isFinite(hours)) return 'Unavailable';
  return hours < 1 ? 'under 1 hour' : `${hours.toFixed(1)} hours`;
}

export function freshnessMessage(result, refreshFailed = false) {
  const schedule = `Scheduled every ${EXPECTED_INTERVAL_HOURS} hours; flagged overdue after ${STALE_AFTER_HOURS} hours.`;
  let message;
  if (result.state === 'stale') message = `Data update overdue. The displayed snapshot or export is at least ${STALE_AFTER_HOURS} hours old. ${schedule}`;
  else if (result.state === 'clock-skew') message = 'Freshness cannot be verified: an export timestamp is ahead of your device clock. Check your clock and the latest pipeline run.';
  else if (result.state === 'unknown') message = 'Freshness unavailable: the export does not contain valid snapshot and publication timestamps.';
  else message = `Data is within the expected refresh window. ${schedule}`;
  return refreshFailed ? `${message} Could not check for a newer export; showing the last data loaded.` : message;
}
