# Operations review: 8 November 2026

This review records a bounded observation of this public project's GitHub Actions runs, followed by a separate local recovery exercise. The history was retrieved on **8 November 2026, 17:15:09–17:16:50 UTC**. Later runs are outside this snapshot.

## Observed pipeline history

The API returned **52 completed pipeline runs: 50 successful and 2 failed**, created between **29 October 2026 00:16:10 UTC** and **8 November 2026 16:42:04 UTC**. The completed-run success rate is **50 / 52 = 96.15%**. The runs comprise 38 scheduled, 13 push-triggered and one manually triggered run.

This is a run outcome measure. It does not measure uptime, an SLA, scheduling punctuality or whether every expected run triggered. The API snapshot contains retained run records and each run's final/current attempt; deleted records and every historical retry attempt are not established by this review.

Evidence: [observed run CSV](operations/2026-11-08-runs.csv) and [summary with API sources](operations/2026-11-08-summary.json). The CSV also includes Pages runs so the two workflow types can be separated.

## Two historical failures

| Run created (UTC) | Observed failure | Publication outcome |
|---|---|---|
| [31 October, 06:31:51](https://github.com/VasilenData/hn-pulse/actions/runs/41176989964) | dbt could not resolve `test_non_negative` and `test_unique_combination`; 7 passed, 3 errors, 21 skipped | Export and commit steps were skipped |
| [31 October, 06:34:17](https://github.com/VasilenData/hn-pulse/actions/runs/41177161940) | All 33 dbt checks/build steps passed, but `git push` was rejected with `fetch-first` because remote `main` contained newer work | Local export completed; publication push failed |

The causes above are recorded in the job logs linked from the summary JSON. The [next recorded successful pipeline run](https://github.com/VasilenData/hn-pulse/actions/runs/41177554902) was manually triggered at 06:40:14 UTC. That establishes a later successful run, not a verified incident recovery duration.

Both failures predate the [8 November reliability change](https://github.com/VasilenData/hn-pulse/pull/2), commit `71f77ee863c4c395948542200f1107c843cabbb9`. The snapshot contains **one observed pipeline run after that change**: [run 42501220461 succeeded](https://github.com/VasilenData/hn-pulse/actions/runs/42501220461). The historical 96.15% rate cannot be credited to the new change or used to estimate a post-change improvement.

## Pages cancellations are separate

The API also returned 67 Pages runs: 47 successful, 20 cancelled and none failed. They are not included in the pipeline success-rate denominator.

For example, [Pages run 42501219610](https://github.com/VasilenData/hn-pulse/actions/runs/42501219610) was cancelled while a newer data-publication deployment was starting. [Run 42501267888](https://github.com/VasilenData/hn-pulse/actions/runs/42501267888) subsequently succeeded for publication commit `595c6c4c83e4f05082316b0130de3f29a5941f1f`. Ordering and commit lineage suggest supersession; the cancellation log alone does not prove the cause. Causes were not individually established for all 20 cancellations, and cancellation is not evidence of site downtime.

## Local recovery exercise — synthetic data

At 17:19:28–17:19:29 UTC, a disposable local exercise copied the exporter and dashboard implementation, created synthetic DuckDB marts, injected failures and retried. This was **an exercise, not a production incident**. No live extraction, deployment or external alert was exercised.

1. A valid two-story export occupied 800 bytes. An injected `OSError` interrupted writing the replacement temporary JSON after 14 bytes. The published file stayed at 800 bytes with the identical SHA-256; no temporary files remained.
2. A synthetic refresh supplied text where a numeric story score was required. The real dashboard script, run with a minimal DOM harness, rejected it, retained the two visible rows and KPI content, and showed the refresh warning.
3. After removing the faults, a valid three-story export occupied 999 bytes. The dashboard loaded it and cleared the failed-refresh warning. The deliberately old synthetic snapshot still showed its overdue-data warning.

The [machine-readable exercise result](operations/2026-11-08-recovery-exercise.json) includes the observed hashes, byte and row counts, expected failures and source provenance. Health metadata was deliberately `null`; no dbt outcomes were invented. Source hashes and Git status were unchanged by the exercise. This does not establish production recovery time or visual browser correctness.

The exercised implementation matched publication commit `595c6c4c83e4f05082316b0130de3f29a5941f1f` after CRLF/LF normalization. The exercise used a local checkout with uncommitted tested changes; it was not represented as a clean checkout. Exact file hashes and the comparison are retained in the JSON. Subsequent code changes require their own verification.

The corresponding failure paths can be reproduced from a checkout with the Python dependencies and Node.js installed:

```bash
python -m pytest -q test_export.py
node --test tests_js/dashboard-data.test.mjs
```

These regression tests cover interrupted/invalid export preservation and an invalid dashboard refresh followed by a valid one. Their fixtures and outputs need not have the same bytes as the separate dated exercise.

## Continue the record

For each future review, record the actual run URL, commit, trigger, UTC timestamps and outcome; then inspect the exported source timestamp and final Pages deployment. Keep cancelled deployments separate from pipeline failures. A blank future log is not operating history, and a configured schedule is not proof of on-time delivery.

Independent overdue-publication alerting and longer observation are still open work. The current dashboard warns when displayed source data or its export is overdue, but it does not notify an operator externally.
