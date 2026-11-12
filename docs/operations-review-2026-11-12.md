# Operating review — 12 November 2026

## What was observed

HN Pulse now has a publication monitor running on Railway, independently of
GitHub Actions scheduling. Its first recorded scheduled check at 17:41 UTC
detected a **real overdue export**: publication age 6.38 hours against the
six-hour threshold. It committed one incident and one pending alert to SQLite
on the mounted volume. That first check was deliberately observe-only, so it
sent no notification.

The normal merge-triggered pipeline subsequently restored a valid publication.
The pipeline and its Pages deployment passed, and a direct external read at
17:54 UTC verified the new export and recorded recovery in local monitor state.
This was a real freshness incident, separate from the controlled delivery drills.

[Machine-readable observation evidence](hosted-monitor-2026-11-12.json)

## Incident timeline

Times are UTC. Scheduled times and observed starts are different facts.

| Observed time | Evidence | Meaning |
| --- | --- | --- |
| 00:45:44 | [Successful scheduled pipeline](https://github.com/VasilenData/hn-pulse/actions/runs/43129653685) | A valid publication was produced at 00:46:21. |
| 08:49:34 | [GitHub publication monitor failed](https://github.com/VasilenData/hn-pulse/actions/runs/43186104371) | It correctly observed publication age 8.05 hours. The monitor was also dependent on GitHub scheduling. |
| 11:17:56 | [Successful scheduled pipeline](https://github.com/VasilenData/hn-pulse/actions/runs/43207935529) | A new source snapshot and publication were produced at 11:18 UTC. |
| 17:38:31 | Railway image build completed | The separate monitor image built successfully from the published source. |
| 17:40:39 | [Merge-triggered pipeline](https://github.com/VasilenData/hn-pulse/actions/runs/43271946360) started | Source commit `e05763b94a6b886e6d89a87fd858849e639419c2`; ordinary extraction, dbt tests and export gates ran. |
| 17:41:21 | First recorded Railway cron observation | The public endpoint still served the 11:18:31 publication. The strict contract passed, freshness failed, and one alert was persisted. No sending occurred in observe-only mode. |
| 17:41:53 | [Pages deployment](https://github.com/VasilenData/hn-pulse/actions/runs/43272034846) completed successfully | Published generated-data commit `4254670f2b4830aa3c781d75b626c830249a82c3`. The deployment log reported success at 17:41:53.848 UTC. |
| 17:43:39 | [GitHub publication monitor](https://github.com/VasilenData/hn-pulse/actions/runs/43272431970) passed | The existing GitHub monitor also observed restored freshness. |
| 17:54:15 | Direct public read by the new worker from a local process | Publication 17:41:06, source 17:41:00; strict validation and freshness passed. Reopened local state recorded the ordered recovery. No local email was sent. |

The run history showed long gaps between scheduled starts, while the observed
pipeline runs completed successfully. That supports a scheduling-gap diagnosis,
**not a proven GitHub infrastructure root cause**. The feature merge triggered
the normal pipeline; the monitor itself did not repair the pipeline.

No freshness timestamp was edited to silence the check. The current API cannot
reconstruct snapshots missed during those gaps, so this review does not claim
zero data loss or an exact outage duration.

## Independent deployment and state

The service uses `Dockerfile.monitor`, a 120-second process deadline, a
`11,41 * * * *` UTC cron schedule, one replica, restart policy `NEVER`, and a
100 MB volume mounted at `/state`. Initial resource ceilings are 0.25 GB RAM and
0.25 vCPU; these are settings, not measured consumption or cost.

Configuration was applied through direct service settings. The deployment
connector rejected the legacy `railwayConfigFile` setting; the checked-in JSON
example was not the deployment mechanism.

The first scheduled process exited 1 because the export was overdue and its
notification was pending. Railway labelled that invocation `CRASHED`; the log
contains a completed structured observation, not a Python exception. This
nonzero result makes an unhealthy check visible to the host. The next scheduled
invocation is still required; automatic process retries are disabled.

## Verification and limits

- The implementation passed 94 Python tests, 14 browser-data tests and a dbt
  build with six models and 27 tests. [PR validation](https://github.com/VasilenData/hn-pulse/actions/runs/43271719987)
  passed before [PR #6](https://github.com/VasilenData/hn-pulse/pull/6) merged.
- The [local HTTP drill](monitor-drill-2026-11-12.json) made actual requests,
  delivered one alert and one recovery, suppressed an alert for the repeated
  unhealthy check, and reopened SQLite between checks. Its outage was synthetic.
- The public JSON contract includes all four marts, completed model/test health,
  timestamp ordering, uniqueness and numeric validity. A fresh but malformed
  export is unhealthy.
- The outbox provides at-least-once delivery. SMTP acceptance can be ambiguous;
  Resend idempotency only deduplicates identical requests within 24 hours.
- The monitor's own scheduler, network, volume and sending provider can still
  fail. It cannot report a complete outage of its own scheduler. One day's
  observations establish no uptime SLA or guaranteed detection interval.

## Controlled email delivery and persistent recovery

At 17:53:57 UTC a one-off Railway invocation ran the controlled email exercise
against a local synthetic fixture. It produced exactly one alert and one
recovery, both accepted by Resend and separately seen in the owner-controlled
Gmail inbox. The repeated unhealthy observation produced no extra message.
The fixture, temporary drill database and real monitor database were separate;
the live publication was untouched.

- [Original hosted drill result](email-drill-2026-11-12.json)
- [Separate inbox receipt verification](email-inbox-verification-2026-11-12.json)

At 17:55:40 UTC a manually invoked normal worker reopened the real
`/state/monitor.sqlite`, observed the recovered public export, and sent the
previously queued real incident alert before its recovery notification.
[The hosted result](hosted-recovery-2026-11-12.json) contains both provider
acceptance IDs, the same public payload hash as the local read, and zero pending
notifications. This demonstrates persistent state across hosted invocations;
it is not a measurement of the cron detection interval.

Both real-incident messages were also opened and verified in the intended inbox
at the displayed 17:55 arrival time. Their bodies identify the same incident
`4d28d417-4147-4092-93aa-a0f1c0132796`: the alert carries the original 17:41
observation, and recovery carries the 17:55 observation. They are separate from
the explicitly labelled controlled exercise.

The normal start command and `11,41 * * * *` cron were restored and verified
at 17:56 UTC, with the deployed source pinned to tested commit `e05763b`.
The resulting normal deployment reached Railway `SUCCESS`.
The first observed incident alert was delayed intentionally while the sender
was configured; it was not delivered at the 17:41 detection time.

The raw drill file retains `email_inbox_receipt_verified: false`: the worker
only observes the provider API, so the separate browser-based inbox check is
recorded separately. Provider acceptance, inbox arrival and human acknowledgement
are different claims.

See the [monitor runbook](INDEPENDENT_MONITOR.md) for deployment, durable
notification semantics and the controlled email exercise.

