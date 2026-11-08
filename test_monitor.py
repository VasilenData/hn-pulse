from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests

import monitor

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def payload(generated="2026-11-08T11:00:00+00:00", newest="2026-11-08T10:00:00+00:00"):
    return {"generated_at": generated, "quality": {"newest_snapshot_at": newest}}


def test_fresh_and_boundary_publications():
    assert monitor.assess(payload(), now=NOW)["status"] == "fresh"
    assert monitor.assess(payload(newest="2026-11-08T06:00:00Z"), now=NOW)["status"] == "fresh"


@pytest.mark.parametrize("field", ["generated", "newest"])
def test_old_source_or_old_publication_is_overdue(field):
    report = monitor.assess(payload(**{field: "2026-11-08T05:59:59Z"}), now=NOW)
    assert report["status"] == "overdue"


@pytest.mark.parametrize("value", [None, {}, [], {"quality": None}, payload(newest="invalid"),
                                 payload(newest="2026-11-08T11:00:00"),
                                 payload(newest="2026-11-08T12:06:00Z")])
def test_bad_or_future_timestamps_are_unavailable(value):
    assert monitor.assess(value, now=NOW)["status"] == "unavailable"


def test_network_failure_is_unavailable_not_overdue(monkeypatch):
    monkeypatch.setattr(monitor.requests, "get", Mock(side_effect=requests.Timeout()))
    report = monitor.observe(now=NOW)
    assert report["status"] == "unavailable"
    assert report["checked_at"] == NOW.isoformat()


@pytest.mark.parametrize("offset", [-12, -5, 0, 5.5, 14])
def test_equivalent_timezone_representations_do_not_change_status_or_age(offset):
    instant = NOW - timedelta(hours=2)
    equivalent = instant.astimezone(timezone(timedelta(hours=offset))).isoformat()
    report = monitor.assess(payload(equivalent, equivalent), now=NOW)
    assert report["status"] == "fresh"
    assert report["source_age_hours"] == 2
    assert report["publication_age_hours"] == 2


def test_fixed_export_ages_monotonically_into_overdue():
    observations = [monitor.assess(payload(), now=NOW + timedelta(hours=i)) for i in range(12)]
    assert [r["source_age_hours"] for r in observations] == sorted(r["source_age_hours"] for r in observations)
    statuses = [r["status"] for r in observations]
    first_overdue = statuses.index("overdue")
    assert set(statuses[first_overdue:]) == {"overdue"}
