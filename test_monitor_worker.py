import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import monitor_worker as worker
from monitor_contract import validate_export

NOW = datetime(2026, 11, 12, 13, tzinfo=timezone.utc)


@pytest.fixture
def export():
    return json.loads((Path(__file__).parent / "docs/data.json").read_text(encoding="utf-8"))


def report(status="overdue", minutes=0):
    return {"checked_at": (NOW + timedelta(minutes=minutes)).isoformat(), "status": status, "url": worker.DEFAULT_URL}


def test_current_export_satisfies_consumer_contract(export):
    assert validate_export(export) is export
    export["mart_top_domains"] = []  # all eligible stories could be internal HN links
    assert validate_export(export) is export


@pytest.mark.parametrize("mutation", [
    lambda d: d.pop("mart_daily_summary"),
    lambda d: d.update(mart_front_page_now=[]),
    lambda d: d["quality"]["tests"].update(fail=1),
    lambda d: d["quality"]["models"].update(success=5),
    lambda d: d["quality"].update(contracts_enforced=0),
    lambda d: d["quality"]["rows"].update(stg_snapshots=False),
    lambda d: d["mart_front_page_now"][0].update(score=float("nan")),
    lambda d: d["mart_front_page_now"][0].update(rank=d["mart_front_page_now"][1]["rank"]),
    lambda d: d["mart_front_page_now"][0].update(story_id=d["mart_front_page_now"][1]["story_id"]),
    lambda d: d["mart_hourly_activity"].append(copy.deepcopy(d["mart_hourly_activity"][0])),
])
def test_fresh_timestamp_cannot_mask_invalid_export(export, mutation):
    mutation(export)
    with pytest.raises(ValueError):
        validate_export(export)


def test_one_alert_per_episode_and_ordered_recovery_survive_restart(tmp_path):
    path = tmp_path / "state.sqlite"
    con = worker.connect(path)
    first = worker.record(con, report())
    assert worker.record(con, report("unavailable", 1)) is None
    con.close()
    con = worker.connect(path)
    recovered = worker.record(con, report("fresh", 2))
    assert recovered["incident_id"] == first["incident_id"]
    assert worker.record(con, report("fresh", 3)) is None
    delivered = []
    worker.deliver(con, lambda e: delivered.append(e) or {"accepted": True}, NOW + timedelta(minutes=4))
    assert [e["kind"] for e in delivered] == ["alert", "recovery"]
    assert worker.deliver(con, lambda e: pytest.fail("duplicate delivery"), NOW + timedelta(minutes=5)) == []
    assert worker.record(con, report("overdue", 6))["incident_id"] != first["incident_id"]
    con.close()


def test_failed_send_remains_pending_and_blocks_recovery(tmp_path):
    con = worker.connect(tmp_path / "state.sqlite")
    worker.record(con, report())
    worker.record(con, report("fresh", 1))
    send = MagicMock(side_effect=TimeoutError("must not leak private server details"))
    failures = worker.deliver(con, send, NOW + timedelta(minutes=2))
    assert send.call_count == 1
    assert failures[0]["error"] == "TimeoutError"
    assert con.execute("SELECT COUNT(*) FROM outbox WHERE delivered_at IS NULL").fetchone()[0] == 2
    assert "private" not in con.execute("SELECT last_error FROM outbox ORDER BY sequence LIMIT 1").fetchone()[0]
    assert worker.deliver(con, send, NOW + timedelta(minutes=2, seconds=30)) == []
    events = []
    worker.deliver(con, lambda e: events.append(e) or {"accepted": True}, NOW + timedelta(minutes=4))
    assert [e["kind"] for e in events] == ["alert", "recovery"]
    con.close()


def test_send_then_process_death_is_retried_with_same_event_identity(tmp_path):
    con = worker.connect(tmp_path / "state.sqlite")
    event = worker.record(con, report())
    with pytest.raises(SystemExit):
        worker.deliver(con, lambda e: (_ for _ in ()).throw(SystemExit()), NOW)
    con.close()
    con = worker.connect(tmp_path / "state.sqlite")
    assert worker.deliver(con, lambda e: pytest.fail("lease is active"), NOW + timedelta(minutes=1)) == []
    events = []
    worker.deliver(con, lambda e: events.append(e) or {"accepted": True}, NOW + timedelta(minutes=6))
    assert events[0]["id"] == event["id"]
    con.close()


@pytest.mark.parametrize("stale_success", [False, True])
def test_expired_sender_cannot_clear_newer_claim_or_release_recovery(tmp_path, stale_success):
    path = tmp_path / "state.sqlite"
    first, second = worker.connect(path), worker.connect(path)
    alert = worker.record(first, report())
    worker.record(first, report("fresh", 1))
    claimed = {}

    def old_transport(event):
        assert event["id"] == alert["id"]
        # The second worker takes over after the first lease expires, then dies
        # before recording acceptance. No sleep or probabilistic scheduling.
        with pytest.raises(SystemExit):
            worker.deliver(second, lambda e: (_ for _ in ()).throw(SystemExit()), NOW + timedelta(minutes=6))
        claimed.update(dict(second.execute("SELECT * FROM outbox WHERE id=?", (event["id"],)).fetchone()))
        if stale_success:
            return {"accepted": True, "message_id": "expired-worker-receipt"}
        raise TimeoutError("expired worker must not clear the replacement claim")

    results = worker.deliver(first, old_transport, NOW)
    assert results[0]["recorded"] is False
    assert results[0]["error"] == "LeaseLost"
    assert results[0]["accepted"] is stale_success
    current = dict(second.execute("SELECT * FROM outbox WHERE id=?", (alert["id"],)).fetchone())
    assert current == claimed
    assert current["attempts"] == 2 and current["delivered_at"] is None
    assert worker.deliver(first, lambda e: pytest.fail("replacement lease must block sending"), NOW + timedelta(minutes=7)) == []
    sent = []
    worker.deliver(second, lambda e: sent.append(e) or {"accepted": True}, NOW + timedelta(minutes=12))
    assert [event["kind"] for event in sent] == ["alert", "recovery"]
    assert sent[0]["id"] == alert["id"]
    first.close()
    second.close()


def test_stale_acknowledgement_cannot_overwrite_newer_delivery_receipt(tmp_path):
    path = tmp_path / "state.sqlite"
    first, second = worker.connect(path), worker.connect(path)
    event = worker.record(first, report())

    def old_transport(_):
        worker.deliver(second, lambda e: {"accepted": True, "message_id": "newer-receipt"}, NOW + timedelta(minutes=6))
        return {"accepted": True, "message_id": "stale-receipt"}

    result = worker.deliver(first, old_transport, NOW)[0]
    assert result["accepted"] is True and result["recorded"] is False
    row = second.execute("SELECT * FROM outbox WHERE id=?", (event["id"],)).fetchone()
    assert json.loads(row["receipt"])["message_id"] == "newer-receipt"
    assert row["delivered_at"] == (NOW + timedelta(minutes=6)).isoformat()
    assert row["lease_token"] is None
    first.close()
    second.close()


@pytest.mark.parametrize("receipt", [None, {"accepted": False}, {"accepted": 1},
                                    {"accepted": True, "invalid": float("nan")}, {"accepted": True, "invalid": object()}])
def test_invalid_acceptance_receipt_cannot_acknowledge_alert_or_release_recovery(tmp_path, receipt):
    con = worker.connect(tmp_path / "state.sqlite")
    worker.record(con, report())
    worker.record(con, report("fresh", 1))
    send = MagicMock(return_value=receipt)
    result = worker.deliver(con, send, NOW + timedelta(minutes=2))
    assert send.call_count == 1
    assert result[0]["accepted"] is False
    assert result[0]["recorded"] is True
    assert con.execute("SELECT COUNT(*) FROM outbox WHERE delivered_at IS NULL").fetchone()[0] == 2
    pending = con.execute("SELECT * FROM outbox ORDER BY sequence LIMIT 1").fetchone()
    assert pending["receipt"] is None and pending["retry_at"] is not None and pending["lease_token"] is None
    con.close()


def test_old_state_schema_migrates_without_losing_pending_event_or_lease(tmp_path):
    path = tmp_path / "state.sqlite"
    con = worker.connect(path)
    event = worker.record(con, report())
    con.execute("ALTER TABLE outbox DROP COLUMN lease_token")
    lease = (NOW + timedelta(minutes=5)).isoformat()
    con.execute("UPDATE outbox SET attempts=1,lease_until=? WHERE id=?", (lease, event["id"]))
    before = dict(con.execute("SELECT * FROM outbox").fetchone())
    con.close()
    con = worker.connect(path)
    after = dict(con.execute("SELECT * FROM outbox").fetchone())
    assert after.pop("lease_token") is None
    assert after == before
    assert worker.deliver(con, lambda e: pytest.fail("old active lease must survive migration"), NOW) == []
    result = worker.deliver(con, lambda e: {"accepted": True}, NOW + timedelta(minutes=6))
    assert result[0]["id"] == event["id"] and result[0]["recorded"] is True
    con.close()


def test_stale_result_or_different_source_cannot_close_live_incident(tmp_path):
    con = worker.connect(tmp_path / "state.sqlite")
    worker.record(con, report())
    with pytest.raises(ValueError, match="time must increase"):
        worker.record(con, report("fresh"))
    changed = report("fresh", 2)
    changed["url"] = "https://example.com/data.json"
    with pytest.raises(ValueError, match="source URL changed"):
        worker.record(con, changed)
    assert con.execute("SELECT COUNT(*) FROM incidents WHERE closed_at IS NULL").fetchone()[0] == 1
    con.close()


def test_drill_scope_does_not_close_live_incident(tmp_path):
    con = worker.connect(tmp_path / "state.sqlite")
    live = worker.record(con, report())
    worker.record(con, report("fresh", 1), scope="drill")
    assert con.execute("SELECT closed_at FROM incidents WHERE id=?", (live["incident_id"],)).fetchone()[0] is None
    con.close()


def test_smtp_uses_verified_tls_and_stable_message_id(monkeypatch):
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value.send_message.return_value = {}
    monkeypatch.setattr(worker.smtplib, "SMTP", smtp)
    send = worker.SMTPTransport({"SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587", "SMTP_SECURITY": "starttls",
                                "SMTP_USER": "sender", "SMTP_PASSWORD": "test-only", "ALERT_FROM": "a@example.test",
                                "ALERT_TO": "b@example.test"})
    event = {"id": "123:alert", "incident_id": "123", "kind": "alert", "scope": "drill", "observation": report()}
    result = send(event)
    client = smtp.return_value.__enter__.return_value
    assert client.starttls.call_count == 1
    assert client.login.call_count == 1
    message = client.send_message.call_args.args[0]
    assert message["Message-ID"] == "<123.alert@hn-pulse.monitor>"
    assert "CONTROLLED DRILL" in message["Subject"]
    assert result["accepted"] is True
    assert "test-only" not in json.dumps(result)


@pytest.mark.parametrize("url", ["http://example.com/data.json", "https://user:secret@example.com/data.json",
                                 "https://example.com/data.json?token=secret", "file:///tmp/data.json"])
def test_unsafe_or_secret_bearing_source_url_is_rejected(url):
    with pytest.raises(ValueError):
        worker.checked_url(url)


def test_smtp_plaintext_is_not_accepted():
    with pytest.raises(ValueError):
        worker.SMTPTransport({"SMTP_HOST": "mail", "ALERT_FROM": "a@example.test", "ALERT_TO": "b@example.test",
                              "SMTP_SECURITY": "none"})


def test_resend_retries_keep_same_key_and_content_and_hide_key(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.json.return_value = {"id": "provider-receipt"}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(worker.requests, "post", post)
    send = worker.ResendTransport({"RESEND_API_KEY": "test-only-secret", "ALERT_FROM": "a@example.test", "ALERT_TO": "b@example.test"})
    event = {"id": "123:alert", "incident_id": "123", "kind": "alert", "scope": "drill", "observation": report()}
    first, second = send(event), send(event)
    assert post.call_args_list[0] == post.call_args_list[1]
    assert post.call_args.kwargs["headers"]["Idempotency-Key"] == event["id"]
    assert first == second == {"transport": "resend", "accepted": True, "message_id": "provider-receipt"}
    assert "test-only-secret" not in json.dumps(first)


def test_http_drill_receives_one_alert_and_recovery_without_changing_export(tmp_path):
    from monitor_drill import run
    result = run(tmp_path / "evidence.json")
    assert [r["event"]["kind"] for r in result["received"]] == ["alert", "recovery"]
    assert result["live_or_committed_export_modified"] is False
    assert result["persistent_state_reopened_each_step"] is True
