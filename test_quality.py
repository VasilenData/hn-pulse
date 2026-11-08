import json
from datetime import datetime, timedelta, timezone

import duckdb
import pytest

import lineage
import quality


def test_age_hours():
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert quality.age_hours(now - timedelta(minutes=90), now) == 1.5


def test_gate_fails_on_stale_data(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(timespec="seconds")
    f = tmp_path / "raw.csv"
    f.write_text(f"snapshot_at,rank\n{old},1\n")
    assert quality.gate(str(f), max_age=1.0) == 1


def test_gate_passes_on_fresh_data(tmp_path):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    f = tmp_path / "raw.csv"
    f.write_text(f"snapshot_at,rank\n{now},1\n")
    assert quality.gate(str(f), max_age=1.0) == 0


def test_gate_fails_on_future_snapshot(tmp_path):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    raw = tmp_path / "raw.csv"
    raw.write_text(f"snapshot_at,rank\n{future},1\n")
    assert quality.gate(str(raw)) == 1


def test_gate_compares_unrounded_age(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=1, seconds=1)).isoformat()
    raw = tmp_path / "raw.csv"
    raw.write_text(f"snapshot_at,rank\n{old},1\n")
    assert quality.gate(str(raw), max_age=1.0) == 1


@pytest.mark.parametrize("contents", ["snapshot_at,rank\n", "snapshot_at,rank\n,1\n", "snapshot_at,rank\ninvalid,1\n"])
def test_gate_fails_cleanly_when_no_valid_timestamp_exists(tmp_path, contents, capsys):
    raw = tmp_path / "raw.csv"
    raw.write_text(contents)
    assert quality.gate(str(raw)) == 1
    assert "FRESHNESS GATE FAILED" in capsys.readouterr().out


def test_gate_fails_cleanly_when_raw_file_is_missing(tmp_path):
    assert quality.gate(str(tmp_path / "missing.csv")) == 1


def test_health_export_preserves_absolute_snapshot_time(tmp_path):
    """An exported age freezes; an absolute UTC timestamp can be aged by any reader."""
    raw = tmp_path / "raw.csv"
    raw.write_text("snapshot_at,rank\n2026-01-01T12:00:00+02:00,1\n2026-01-01T11:00:00Z,2\n")
    db = tmp_path / "sample.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("create table stg_snapshots as select * from range(2)")
        con.execute("create table fct_stories as select * from range(1)")
    results = tmp_path / "run_results.json"
    results.write_text(json.dumps({"results": [{"unique_id": "test.x.example", "status": "pass"}]}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": {
        "model.x.example": {"resource_type": "model", "contract": {"enforced": True}},
    }}))

    report = quality.build(str(db), str(raw), str(results), str(manifest))

    assert report["newest_snapshot_at"] == "2026-01-01T11:00:00+00:00"
    # Older cached pages call .toFixed() on this numeric field during a rolling deployment.
    assert isinstance(report["newest_snapshot_age_hours"], (int, float))
    expected_age = (datetime.now(timezone.utc) - datetime.fromisoformat(report["newest_snapshot_at"])).total_seconds() / 3600
    assert abs(report["newest_snapshot_age_hours"] - expected_age) < 0.02
    assert report["rows"] == {"stg_snapshots": 2, "fct_stories": 1}
    assert json.loads(json.dumps(report))["newest_snapshot_at"] == report["newest_snapshot_at"]


def test_summarise_run_counts_tests_and_models(tmp_path):
    p = tmp_path / "run_results.json"
    p.write_text(json.dumps({"results": [
        {"unique_id": "model.x.a", "status": "success"},
        {"unique_id": "model.x.b", "status": "error"},
        {"unique_id": "test.x.t1", "status": "pass"},
        {"unique_id": "test.x.t2", "status": "fail"},
        {"unique_id": "test.x.t3", "status": "pass"},
    ]}))
    s = quality.summarise_run(str(p))
    assert s["tests"] == {"pass": 2, "warn": 0, "fail": 1, "error": 0}
    assert s["models"] == {"success": 1, "error": 1}


def test_lineage_mermaid_links_models():
    manifest = {"nodes": {
        "model.x.stg": {"resource_type": "model", "name": "stg", "depends_on": {"nodes": []}},
        "model.x.fct": {"resource_type": "model", "name": "fct", "depends_on": {"nodes": ["model.x.stg"]}},
        "test.x.t": {"resource_type": "test", "name": "t", "depends_on": {"nodes": ["model.x.fct"]}},
    }}
    out = lineage.mermaid(manifest)
    assert "raw --> stg" in out and "stg --> fct" in out and "test" not in out
