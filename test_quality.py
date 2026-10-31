import json
from datetime import datetime, timedelta, timezone

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
