"""Independent cron monitor with durable incident/outbox state and SMTP alerts.

    python monitor_worker.py --state /state/monitor.sqlite

SMTP credentials belong only in the deployment environment. No web server or
public inbound port is needed. One cron service owns the mounted state volume.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import smtplib
import sqlite3
import ssl
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

import requests

from monitor import DEFAULT_URL, assess
from monitor_contract import validate_export

MAX_BYTES = 2 * 1024 * 1024
MAX_ATTEMPTS_PER_RUN = 4
ROOT = Path(__file__).resolve().parent


def utcnow():
    return datetime.now(timezone.utc)


def fingerprint():
    digest = hashlib.sha256()
    for name in ("monitor_worker.py", "monitor_contract.py", "monitor.py"):
        digest.update((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def checked_url(value, allow_local=False):
    parts = urlsplit(value)
    local = parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.username or parts.password or parts.fragment or parts.query or not parts.hostname:
        raise ValueError("URL must not contain credentials, fragments or query parameters")
    if parts.scheme != "https" and not (allow_local and local):
        raise ValueError("URL must use HTTPS (localhost HTTP is allowed only for the drill)")
    return value


def observe(url=DEFAULT_URL, now=None, allow_local=False):
    now = now or utcnow()
    checked_url(url, allow_local=allow_local)
    try:
        # Connect and read *inactivity* limits; these are not a hard wall-clock deadline.
        with requests.get(url, timeout=(5, 10), stream=True, allow_redirects=False,
                          headers={"Cache-Control": "no-cache", "User-Agent": "HN-Pulse-publication-monitor/1"}) as response:
            if response.status_code != 200:
                raise ValueError(f"unexpected HTTP status {response.status_code}")
            data = bytearray()
            started = time.monotonic()
            for chunk in response.iter_content(8192):
                data.extend(chunk)
                if len(data) > MAX_BYTES or time.monotonic() - started > 30:
                    raise ValueError("export exceeded monitor byte/time budget")
            payload = json.loads(data)
            validate_export(payload)
            report = assess(payload, now=now)
            if report["status"] != "unavailable":
                source = datetime.fromisoformat(report["newest_snapshot_at"])
                publication = datetime.fromisoformat(report["generated_at"])
                if source > publication + timedelta(minutes=5):
                    raise ValueError("source timestamp is later than publication")
            report["payload_sha256"] = hashlib.sha256(data).hexdigest()
            report["payload_bytes"] = len(data)
    except (requests.RequestException, ValueError, TypeError, KeyError, OverflowError) as error:
        # Do not put exception URLs/headers or service credentials into logs/alerts.
        reason = str(error) if isinstance(error, ValueError) and not isinstance(error, requests.RequestException) else type(error).__name__
        report = {"checked_at": now.isoformat(), "status": "unavailable", "reason": reason[:200]}
    report.update(url=url, monitor_code_sha256=fingerprint())
    return report


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS observations (
          id INTEGER PRIMARY KEY, scope TEXT NOT NULL, checked_at TEXT NOT NULL, report TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents (
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_incident ON incidents(scope) WHERE closed_at IS NULL;
        CREATE TABLE IF NOT EXISTS outbox (
          sequence INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, incident_id TEXT NOT NULL,
          kind TEXT NOT NULL, body TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          delivered_at TEXT, receipt TEXT, retry_at TEXT, lease_until TEXT, last_error TEXT);
    """)
    return con


def record(con, report, scope="live"):
    """Record state transition and notification intent in the same transaction."""
    if report["status"] not in ("fresh", "overdue", "unavailable"):
        raise ValueError("unsupported observation status")
    checked_at = report["checked_at"]
    if datetime.fromisoformat(checked_at).tzinfo is None:
        raise ValueError("checked_at must include timezone")
    body = json.dumps(report, sort_keys=True, allow_nan=False)
    con.execute("BEGIN IMMEDIATE")
    try:
        prior = con.execute("SELECT checked_at,report FROM observations WHERE scope=? ORDER BY id DESC LIMIT 1", (scope,)).fetchone()
        if prior and datetime.fromisoformat(checked_at) <= datetime.fromisoformat(prior["checked_at"]):
            raise ValueError("observation time must increase; refusing stale concurrent result")
        if prior and json.loads(prior["report"])["url"] != report["url"]:
            raise ValueError("source URL changed; use a new state database")
        con.execute("INSERT INTO observations(scope,checked_at,report) VALUES (?,?,?)", (scope, checked_at, body))
        active = con.execute("SELECT * FROM incidents WHERE scope=? AND closed_at IS NULL", (scope,)).fetchone()
        event = None
        if report["status"] != "fresh" and active is None:
            incident = str(uuid.uuid4())
            con.execute("INSERT INTO incidents(id,scope,opened_at) VALUES (?,?,?)", (incident, scope, checked_at))
            event = {"incident_id": incident, "kind": "alert", "scope": scope, "observation": report}
        elif report["status"] == "fresh" and active:
            con.execute("UPDATE incidents SET closed_at=? WHERE id=?", (checked_at, active["id"]))
            event = {"incident_id": active["id"], "kind": "recovery", "scope": scope, "observation": report}
        if event:
            event["id"] = f"{event['incident_id']}:{event['kind']}"
            con.execute("INSERT INTO outbox(id,incident_id,kind,body) VALUES (?,?,?,?)",
                        (event["id"], event["incident_id"], event["kind"], json.dumps(event, sort_keys=True)))
        # Keep 90 days of detailed observations; incidents and delivery receipts remain.
        cutoff = (datetime.fromisoformat(checked_at) - timedelta(days=90)).isoformat()
        con.execute("DELETE FROM observations WHERE scope=? AND checked_at < ?", (scope, cutoff))
        con.commit()
        return event
    except BaseException:
        con.rollback()
        raise


def event_text(event):
    observation = event["observation"]
    prefix = "[CONTROLLED DRILL] " if event["scope"] != "live" else ""
    subject = f"{prefix}HN Pulse {event['kind']}: {observation['status']}"
    text = (f"{subject}\nObserved at: {observation['checked_at']}\n"
            f"Public export: {observation['url']}\nEvent ID: {event['id']}\n"
            f"Details: {json.dumps(observation, sort_keys=True)}\n\n"
            "An unavailable observation does not establish data loss. "
            "This monitor cannot detect its own complete scheduler/provider outage.")
    return subject, text


class SMTPTransport:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.host = env.get("SMTP_HOST", "")
        self.port = int(env.get("SMTP_PORT", "465"))
        self.security = env.get("SMTP_SECURITY", "ssl")
        self.user, self.password = env.get("SMTP_USER"), env.get("SMTP_PASSWORD")
        self.sender, self.recipient = env.get("ALERT_FROM", ""), env.get("ALERT_TO", "")
        if not self.host or not self.sender or not self.recipient:
            raise ValueError("SMTP_HOST, ALERT_FROM and ALERT_TO are required")
        if self.security not in ("ssl", "starttls"):
            raise ValueError("SMTP_SECURITY must be ssl or starttls")
        if bool(self.user) != bool(self.password):
            raise ValueError("SMTP_USER and SMTP_PASSWORD must be supplied together")
        for address in (self.sender, self.recipient):
            if "\n" in address or "\r" in address or "," in address or address.count("@") != 1:
                raise ValueError("Use one plain sender and recipient email address")

    def __call__(self, event):
        subject, text = event_text(event)
        message = EmailMessage()
        message["Subject"], message["From"], message["To"] = subject, self.sender, self.recipient
        message["Message-ID"] = f"<{event['id'].replace(':', '.')}@hn-pulse.monitor>"
        message["Resend-Idempotency-Key"] = event["id"]
        message.set_content(text)
        context = ssl.create_default_context()
        cls = smtplib.SMTP_SSL if self.security == "ssl" else smtplib.SMTP
        kwargs = {"timeout": 15}
        if self.security == "ssl":
            kwargs["context"] = context
        with cls(self.host, self.port, **kwargs) as client:
            if self.security == "starttls":
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if self.user:
                client.login(self.user, self.password)
            refused = client.send_message(message)
            if refused:
                raise ValueError("SMTP server refused the recipient")
        # Accepted by sending server != received/read by the person.
        return {"transport": "smtp", "accepted": True, "message_id": message["Message-ID"]}


class ResendTransport:
    """Direct HTTPS email adapter with provider idempotency (24-hour retention)."""
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.key = env.get("RESEND_API_KEY")
        self.sender, self.recipient = env.get("ALERT_FROM", ""), env.get("ALERT_TO", "")
        if not self.key or not self.sender or not self.recipient:
            raise ValueError("RESEND_API_KEY, ALERT_FROM and ALERT_TO are required")
        for address in (self.sender, self.recipient):
            if "\n" in address or "\r" in address or "," in address or address.count("@") != 1:
                raise ValueError("Use one plain sender and recipient email address")

    def __call__(self, event):
        subject, text = event_text(event)
        with requests.post("https://api.resend.com/emails", timeout=(5, 15), allow_redirects=False,
                           headers={"Authorization": f"Bearer {self.key}", "Idempotency-Key": event["id"]},
                           json={"from": self.sender, "to": [self.recipient], "subject": subject, "text": text}) as response:
            if not 200 <= response.status_code < 300:
                raise ValueError(f"email service HTTP status {response.status_code}")
            receipt = response.json()
            if not isinstance(receipt, dict) or not isinstance(receipt.get("id"), str) or not receipt["id"]:
                raise ValueError("email service returned no message id")
        return {"transport": "resend", "accepted": True, "message_id": receipt["id"]}


def email_transport():
    kind = os.getenv("ALERT_TRANSPORT", "resend")
    if kind == "resend":
        return ResendTransport()
    if kind == "smtp":
        return SMTPTransport()
    raise ValueError("ALERT_TRANSPORT must be resend or smtp")


class WebhookTransport:
    """Optional user-controlled receiver; used by the local delivery drill."""
    def __init__(self, url, allow_local=False):
        self.url = checked_url(url, allow_local=allow_local)

    def __call__(self, event):
        with requests.post(self.url, json=event, timeout=(5, 10), allow_redirects=False,
                           headers={"Idempotency-Key": event["id"]}) as response:
            if not 200 <= response.status_code < 300:
                raise ValueError(f"notification HTTP status {response.status_code}")
        return {"transport": "webhook", "accepted": True, "http_status": response.status_code}


def deliver(con, transport, now=None):
    """At-least-once delivery. Never acknowledge a failed send or reorder recovery."""
    now = now or utcnow()
    results = []
    for _ in range(MAX_ATTEMPTS_PER_RUN):
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM outbox WHERE delivered_at IS NULL ORDER BY sequence LIMIT 1").fetchone()
        if not row or (row["retry_at"] and datetime.fromisoformat(row["retry_at"]) > now) or (row["lease_until"] and datetime.fromisoformat(row["lease_until"]) > now):
            con.commit()
            break
        con.execute("UPDATE outbox SET attempts=attempts+1, lease_until=? WHERE id=?",
                    ((now + timedelta(minutes=5)).isoformat(), row["id"]))
        con.commit()
        try:
            receipt = transport(json.loads(row["body"]))
        except Exception as error:
            # Deliberately exclude exception text (SMTP response may include a recipient).
            delay = min(3600, 60 * 2 ** min(row["attempts"], 6))
            con.execute("UPDATE outbox SET retry_at=?,lease_until=NULL,last_error=? WHERE id=?",
                        ((now + timedelta(seconds=delay)).isoformat(), type(error).__name__, row["id"]))
            results.append({"id": row["id"], "accepted": False, "error": type(error).__name__})
            break
        else:
            con.execute("UPDATE outbox SET delivered_at=?,receipt=?,lease_until=NULL,retry_at=NULL,last_error=NULL WHERE id=?",
                        (now.isoformat(), json.dumps(receipt, sort_keys=True), row["id"]))
            results.append({"id": row["id"], **receipt})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path(os.getenv("MONITOR_STATE", "/state/monitor.sqlite")))
    parser.add_argument("--url", default=os.getenv("MONITOR_URL", DEFAULT_URL))
    parser.add_argument("--observe-only", action="store_true", default=os.getenv("MONITOR_OBSERVE_ONLY", "false").lower() == "true",
                        help="Record observations without configuring/sending notifications (or MONITOR_OBSERVE_ONLY=true)")
    args = parser.parse_args()
    report = observe(args.url)
    with connect(args.state) as con:
        event = record(con, report)
        deliveries, configuration_error = [], None
        if not args.observe_only:
            try:
                deliveries = deliver(con, email_transport())
            except (ValueError, OSError):
                configuration_error = "Email configuration unavailable; durable pending notifications retained"
        pending = con.execute("SELECT COUNT(*) FROM outbox WHERE delivered_at IS NULL").fetchone()[0]
        summary = {"observation": report, "transition": event["kind"] if event else None,
                   "deliveries": deliveries, "pending_notifications": pending,
                   "notification_mode": "observe_only" if args.observe_only else os.getenv("ALERT_TRANSPORT", "resend")}
        if configuration_error:
            summary["configuration_error"] = configuration_error
        print(json.dumps(summary, sort_keys=True))
    return 0 if report["status"] == "fresh" and not pending and not configuration_error else 1


if __name__ == "__main__":
    sys.exit(main())
