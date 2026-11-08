import assert from 'node:assert/strict';
import test from 'node:test';
import {assessFreshness, formatAge, freshnessMessage} from '../docs/freshness.mjs';

const at = value => Date.parse(`2026-01-01T${value}:00Z`);
const payload = (snapshot = '12:00', publication = '12:01') => ({
  generated_at: `2026-01-01T${publication}:00+00:00`,
  quality: {newest_snapshot_at: `2026-01-01T${snapshot}:00+00:00`},
});

test('the same successful export becomes overdue as real time passes', () => {
  const data = payload();
  data.quality.newest_snapshot_age_hours = 0; // A legacy value must never keep the page green.
  assert.equal(assessFreshness(data, at('12:30')).state, 'fresh');
  const later = assessFreshness(data, at('18:30'));
  assert.equal(later.state, 'stale');
  assert.equal(later.snapshotAgeHours, 6.5);
  assert.equal(formatAge(later.snapshotAgeHours), '6.5 hours');
});

test('a newly generated export cannot hide old source data', () => {
  const result = assessFreshness(payload('05:00', '12:00'), at('12:01'));
  assert.equal(result.state, 'stale');
  assert.ok(result.publicationAgeHours < 1);
});

test('publication age is checked as well as source age', () => {
  const result = assessFreshness(payload('12:00', '05:00'), at('12:01'));
  assert.equal(result.state, 'stale');
});

test('a three-hour schedule allows a delayed run but flags six hours', () => {
  assert.equal(assessFreshness(payload(), at('17:59')).state, 'fresh');
  assert.equal(assessFreshness(payload(), at('18:00')).state, 'stale');
});

test('older exported mart timestamps are interpreted as UTC, including outside UTC', () => {
  const oldTimezone = process.env.TZ;
  process.env.TZ = 'America/Los_Angeles';
  try {
    const data = {generated_at: '2026-01-01T12:01:00Z', quality: {newest_snapshot_age_hours: 0}, mart_front_page_now: [
      {snapshot_at: '2026-01-01T11:00:00'},
      {snapshot_at: '2026-01-01T12:00:00'},
    ]};
    assert.equal(assessFreshness(data, at('12:30')).snapshotAgeHours, 0.5);
  } finally {
    if (oldTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = oldTimezone;
  }
});

test('timezone offsets preserve the instant of the newest snapshot', () => {
  const data = payload();
  data.quality.newest_snapshot_at = '2026-01-01T14:00:00+02:00';
  assert.equal(assessFreshness(data, at('12:30')).snapshotAgeHours, 0.5);
});

test('missing or invalid timestamps are unavailable, never fresh', () => {
  for (const data of [{}, {generated_at: 'invalid'}, payload()]) {
    if (data.quality) data.quality.newest_snapshot_at = 'invalid';
    const result = assessFreshness(data, at('12:30'));
    assert.equal(result.state, 'unknown');
    assert.equal(formatAge(result.snapshotAgeHours), 'Unavailable');
  }
});

test('a malformed explicit snapshot timestamp cannot be hidden by a legacy fallback', () => {
  const data = payload();
  data.quality.newest_snapshot_at = 'invalid';
  data.mart_front_page_now = [{snapshot_at: '2026-01-01T12:00:00'}];
  assert.equal(assessFreshness(data, at('12:30')).state, 'unknown');
});

test('large future timestamps report clock skew rather than negative age or freshness', () => {
  assert.equal(assessFreshness(payload(), at('11:00')).state, 'clock-skew');
  const smallSkew = assessFreshness(payload(), at('11:59'));
  assert.equal(smallSkew.state, 'fresh');
  assert.equal(smallSkew.snapshotAgeHours, 0);
});

test('a failed refresh preserves the overdue warning and explains retained data', () => {
  const result = assessFreshness(payload(), at('19:00'));
  const message = freshnessMessage(result, true);
  assert.match(message, /Data update overdue/);
  assert.match(message, /Scheduled every 3 hours/);
  assert.match(message, /Could not check for a newer export/);
});
