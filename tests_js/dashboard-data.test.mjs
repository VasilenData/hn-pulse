import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import {fetchDashboardData, validateDashboardData} from '../docs/dashboard-data.mjs';
import {assessFreshness, formatAge, freshnessMessage} from '../docs/freshness.mjs';

const payload = () => ({
  generated_at: '2026-01-01T12:01:00Z',
  mart_daily_summary: [{snapshots: 4}],
  mart_front_page_now: [{rank: 1, title: 'A story', domain: 'example.com', score: 42, comments: 7}],
  mart_top_domains: [{domain: 'example.com', stories: 2}],
  mart_hourly_activity: [{posted_hour_utc: 12, avg_peak_score: 42}],
  quality: {
    newest_snapshot_at: '2026-01-01T12:00:00Z',
    tests: {pass: 27, warn: 0, fail: 0, error: 0},
    contracts_enforced: 6, models_total: 6,
    rows: {stg_snapshots: 400, fct_stories: 200},
  },
});

test('accepts current exports and a legacy export without quality metadata', () => {
  const data = payload();
  assert.equal(validateDashboardData(data), data);
  data.quality = null;
  assert.equal(validateDashboardData(data), data);
});

test('rejects invalid nested fields before they can damage a rendered dashboard', () => {
  const changes = [
    data => {data.quality.tests = null;},
    data => {data.quality.rows.fct_stories = '200';},
    data => {data.mart_front_page_now = [null];},
    data => {data.mart_front_page_now[0].score = '<img src=x onerror=alert(1)>';},
    data => {data.mart_daily_summary[0].snapshots = -1;},
    data => {data.mart_hourly_activity[0].avg_peak_score = NaN;},
    data => {data.mart_hourly_activity[0].posted_hour_utc = 24;},
    data => {data.mart_top_domains[0].stories = Infinity;},
  ];
  for (const change of changes) {
    const data = payload();
    change(data);
    assert.throws(() => validateDashboardData(data), /invalid/);
  }
});

test('fetch bypasses caches, has a bounded lifetime, and validates the response', async () => {
  const data = payload();
  const result = await fetchDashboardData(async (url, options) => {
    assert.equal(url, 'data.json');
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal instanceof AbortSignal);
    return {ok: true, json: async () => data};
  });
  assert.equal(result, data);
  await assert.rejects(fetchDashboardData(async () => ({ok: false})), /unavailable/);
  await assert.rejects(fetchDashboardData(async () => ({ok: true, json: async () => ({})})), /invalid/);
});

test('an invalid refresh keeps the displayed last good export, then a later valid refresh recovers', async () => {
  const html = await readFile(new URL('../docs/index.html', import.meta.url), 'utf8');
  const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1].replace(/^import .*;$/gm, '');
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent: '', innerHTML: '', dataset: {}});
    return nodes.get(id);
  };
  let next = payload();
  const context = vm.createContext({
    assessFreshness, formatAge, freshnessMessage,
    fetchDashboardData: async () => validateDashboardData(next),
    document: {
      getElementById: id => id === 'load-error' ? null : node(id),
      querySelector: node,
      addEventListener() {},
    },
    setInterval() {}, console,
  });
  vm.runInContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  const table = node('#t tbody').innerHTML;
  const generated = node('gen').textContent;
  assert.match(table, /A story/);

  next = payload();
  next.generated_at = '2026-01-02T12:01:00Z';
  next.quality.rows = null;
  await vm.runInContext('refreshDashboard()', context);
  assert.equal(node('#t tbody').innerHTML, table);
  assert.equal(node('gen').textContent, generated);
  assert.match(node('freshness-status').textContent, /Could not check for a newer export/);

  next = payload();
  next.mart_front_page_now[0].title = 'New story';
  next.mart_front_page_now[0].rank = 2; // Rank #1 may have been deleted during extraction.
  await vm.runInContext('refreshDashboard()', context);
  assert.match(node('#t tbody').innerHTML, /New story/);
  assert.match(node('kpis').innerHTML, /Score of the #2 story/);
  assert.doesNotMatch(node('freshness-status').textContent, /Could not check for a newer export/);
});
