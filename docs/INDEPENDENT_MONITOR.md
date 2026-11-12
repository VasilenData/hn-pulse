# Independent publication monitoring

The existing hourly GitHub workflow remains useful as an observation history. The
worker runs on Railway and notifies the owner through Resend when the public
export becomes overdue, malformed or unavailable. It does not extract data, run
dbt, write to GitHub or modify the live dashboard.

## Evidence and current scope

- [Controlled HTTP delivery drill](monitor-drill-2026-11-12.json): real
  local HTTP GET/POST requests, a synthetic seven-hour-old source timestamp,
  exactly one alert and one recovery received, and SQLite reopened between checks.
  The committed export and live site were not changed.
- `test_monitor_worker.py` exercises failed sending, durable retry, ordered
  recovery, repeated observations, replay after a crash, strict output checks and
  email request construction. SMTP/Resend tests use test doubles; these do not
  prove real email delivery.
- The [12 November operating review](operations-review-2026-11-12.md) records
  an actual scheduled Railway observation, a real stale-publication incident,
  recovery with the persistent outbox, and restored normal cron configuration.
- The [hosted email drill](email-drill-2026-11-12.json) recorded two Resend
  acceptances. Both controlled messages were separately verified in the
  owner-controlled Gmail inbox; [receipt verification](email-inbox-verification-2026-11-12.json)
  remains separate from the process-generated JSON. The drill process cannot
  inspect an inbox, so its original inbox-verification field stays false.
- These are dated observations, not evidence of long-term uptime. Provider
  acceptance alone is not evidence of inbox delivery or a human acknowledgement.

## Checks and the contract

The source and publication timestamps must be within six hours and no more than
five minutes in the future. The source cannot be later than its publication by
more than the clock tolerance. A fresh timestamp does not make a broken export
healthy: all four mart structures, front-page story/rank keys, consumer-visible
numeric fields, completed tests, successful models and enforced contracts are
validated. The front-page mart contains 30 stories; missing ranks within the
source's top 100 are allowed because extraction accepts 90/100 stories.

An unreachable, oversized, malformed, redirected or failed-health export is
`unavailable`, not evidence of lost source data. An old otherwise valid export is
`overdue`. The HTTP body is limited to 2 MiB. Connect/read inactivity limits are
5/10 seconds, with an elapsed-time check between chunks. The container's `timeout
120s` command supplies the hard process deadline; a killed check cannot send its
own failure notice.

## Durable notifications

SQLite stores observations, incidents and an outbox on `/state`. The observation,
incident transition and notification intent commit together. One unhealthy
episode produces one initial alert; consecutive unhealthy observations remain
in the same episode. A later healthy check queues one recovery. A subsequent
failure starts a new episode. A changed source URL requires a new state database.

Unacknowledged events remain pending across restarts. Sending is ordered, so a
recovery cannot overtake its alert. A five-minute lease limits concurrent sending;
failed attempts use backoff capped at one hour. At most four events are attempted
per invocation. Observations are retained for 90 days; incident and delivery
records remain until deliberately archived by the operator.

Delivery is **at least once**, not universally exactly once. If the provider
accepts a message and the worker dies before saving the receipt, the same event
ID is retried. Generic SMTP may deliver a duplicate. Resend's idempotency keys
deduplicate identical requests for 24 hours; a retry after that interval can
duplicate a message. Do not change sender/recipient while pending events exist:
the request associated with an idempotency key must remain unchanged. No heartbeat
message or repeated reminder is sent during a continuing incident.

## Railway deployment

Set the Dockerfile path to `Dockerfile.monitor`, start command to
`timeout 120s python monitor_worker.py`, cron to `11,41 * * * *` and restart policy
to `NEVER` in the service settings. The deployment connector rejected the legacy
`railwayConfigFile` setting on 12 November 2026; `railway.monitor.json` is retained
only as a legacy configuration example, not evidence of an applied deployment.
Mount one persistent volume at `/state`, use one replica and keep cron runs non-overlapping.
The configured schedule is minute 11 and 41 of every hour; it is a schedule, not a
guaranteed detection time. No HTTP domain, public port or database proxy is needed.
Suggested initial bounds: 0.25 GB RAM and 0.25 vCPU. Observe actual consumption;
these are resource ceilings, not measured usage or a price estimate.

Set variables in the provider's secret settings, never in this repository:

| Variable | Purpose |
| --- | --- |
| `MONITOR_STATE` | `/state/monitor.sqlite` |
| `MONITOR_URL` | `https://vasilendata.github.io/hn-pulse/data.json` |
| `MONITOR_OBSERVE_ONLY` | `true` to suppress sending during initial setup (default `false`) |
| `ALERT_TRANSPORT` | `resend` (default) or `smtp` |
| `ALERT_FROM` | Sender permitted by the sending service |
| `ALERT_TO` | One owner-controlled recipient |
| `RESEND_API_KEY` | Required for the Resend HTTPS adapter |
| `SMTP_HOST`, `SMTP_PORT` | SMTP server and port, if using SMTP |
| `SMTP_SECURITY` | `ssl` (default) or `starttls`; plaintext is rejected |
| `SMTP_USER`, `SMTP_PASSWORD` | Optional paired SMTP authentication values |

Resend uses HTTPS `POST /emails`, a stable `Idempotency-Key` and the returned
message ID as acceptance evidence. A test-domain sender may only reach permitted
recipients; follow the sending provider's account restrictions. SMTP requires
verified TLS. Logs exclude credentials, sender/recipient values and SMTP response
text. Public export timestamps and identifiers are included in alerts.

The worker runs in observe-only mode if started explicitly with:

```sh
timeout 120s python monitor_worker.py --observe-only
```

Set `MONITOR_OBSERVE_ONLY=true` for initial setup without changing the start command.
If using a platform that still supports legacy config-as-code, its start command
can override the dashboard start command. Observe-only mode still stores incidents
and pending notifications. Switching to
delivery mode sends those queued events in order. Review old pending events before
enabling a newly configured recipient. If email configuration is missing, normal
mode fails and retains pending notifications rather than claiming success.

## Controlled delivery exercise

Local exercise, with no real email or live-site changes:

```sh
python monitor_drill.py --output /tmp/hn-drill.json
```

After the owner has configured the sending account, send two explicitly labelled
drill messages and preserve the acceptance receipts:

```sh
timeout 120s python monitor_drill.py --email --output /state/email-drill-YYYY-MM-DD.json
```

The output path must not already exist, preventing accidental overwriting of
evidence. Verify both messages in the intended inbox and record their receipt
times separately. Restore the ordinary `monitor_worker.py` start command after a
one-off deployment drill. The test uses a local fixture and separate temporary
SQLite state, so it cannot open or close the live monitor's incident.

## Responding to an alert

1. Compare source and export timestamps. An export can be new while its source is old.
2. Inspect the pipeline's latest run and the public JSON. A transport error is a
   monitoring failure until the source is independently inspected.
3. Repair the underlying pipeline/configuration and let a valid publication pass
   all existing dbt checks. Do not change an old timestamp to silence the monitor.
4. Confirm a fresh external observation and the recovery message. Write a short
   incident record distinguishing an actual fault from a controlled exercise.

Railway independence removes the shared GitHub scheduler dependency. It does not
make the monitor independent of its own provider, volume, network or email
service. A complete scheduler outage cannot report itself. State loss can cause
another initial alert. This project does not claim an uptime SLA.

References: [Resend send API](https://resend.com/docs/api-reference/emails/send-email),
[Resend idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys),
[Python SMTP](https://docs.python.org/3/library/smtplib.html).
