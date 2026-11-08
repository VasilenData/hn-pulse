"""Data-quality helpers: a freshness gate and a machine-readable health report.

* `python quality.py gate`  exits non-zero if the newest snapshot is too old (used right after extract).
* `build()` summarises the last `dbt build` (tests, contracts, row counts) for the dashboard.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import duckdb

ROOT = os.path.dirname(__file__)
RAW = os.path.join(ROOT, "data", "raw_snapshots.csv")
RUN_RESULTS = os.path.join(ROOT, "target", "run_results.json")
MANIFEST = os.path.join(ROOT, "target", "manifest.json")
DB_PATH = os.path.join(ROOT, "target", "hn_pulse.duckdb")
MAX_AGE_HOURS = 1.0  # the gate runs straight after extract, so the newest snapshot must be recent
MAX_FUTURE_SECONDS = 5 * 60


def latest_snapshot(raw: str = RAW) -> datetime:
    with duckdb.connect() as con:
        # Fetch a numeric instant rather than a TIMESTAMPTZ Python object: the
        # latter makes DuckDB depend on optional pytz merely to read UTC data.
        ts = con.execute("select epoch(max(cast(snapshot_at as timestamptz))) "
                         "from read_csv_auto(?, header=true)", [raw]).fetchone()[0]
    if ts is None:
        raise ValueError("No snapshot timestamp was found")
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def age_hours(ts: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return round((now - ts).total_seconds() / 3600, 2)


def summarise_run(path: str = RUN_RESULTS) -> dict:
    """Count dbt results by kind. Tests are nodes whose unique_id starts with 'test.'."""
    with open(path, encoding="utf-8") as fh:
        results = json.load(fh)["results"]
    out = {"tests": {"pass": 0, "warn": 0, "fail": 0, "error": 0}, "models": {"success": 0, "error": 0}}
    for r in results:
        kind = "tests" if r["unique_id"].startswith("test.") else "models" if r["unique_id"].startswith("model.") else None
        if kind == "tests":
            out["tests"][r["status"] if r["status"] in out["tests"] else "error"] += 1
        elif kind == "models":
            out["models"]["success" if r["status"] == "success" else "error"] += 1
    return out


def contracts_enforced(path: str = MANIFEST) -> tuple[int, int]:
    with open(path, encoding="utf-8") as fh:
        nodes = [n for n in json.load(fh)["nodes"].values() if n["resource_type"] == "model"]
    return sum(1 for n in nodes if n["contract"]["enforced"]), len(nodes)


def build(db_path: str = DB_PATH, raw: str = RAW, run_results: str = RUN_RESULTS, manifest: str = MANIFEST) -> dict:
    """The block shown in the dashboard's pipeline-health section. Raises if dbt artefacts are missing."""
    run = summarise_run(run_results)
    enforced, models = contracts_enforced(manifest)
    con = duckdb.connect(db_path, read_only=True)
    rows = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("stg_snapshots", "fct_stories")}
    con.close()
    newest = latest_snapshot(raw)
    return {"tests": run["tests"], "models": run["models"], "contracts_enforced": enforced, "models_total": models,
            "rows": rows, "newest_snapshot_at": newest.isoformat(timespec="seconds"),
            # Deprecated: retained for cached dashboard clients. New clients calculate current age from the timestamp.
            "newest_snapshot_age_hours": age_hours(newest)}


def gate(raw: str = RAW, max_age: float = MAX_AGE_HOURS) -> int:
    try:
        newest = latest_snapshot(raw)
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"FRESHNESS GATE FAILED: cannot read a valid snapshot ({error})")
        return 1
    seconds = (datetime.now(timezone.utc) - newest).total_seconds()
    if seconds < -MAX_FUTURE_SECONDS:
        print("FRESHNESS GATE FAILED: newest snapshot is more than five minutes in the future")
        return 1
    age = seconds / 3600
    if age > max_age:
        print(f"FRESHNESS GATE FAILED: newest snapshot is {age:.2f}h old (limit {max_age}h)")
        return 1
    print(f"freshness ok: newest snapshot is {max(0, age):.2f}h old")
    return 0


if __name__ == "__main__":
    sys.exit(gate() if sys.argv[1:] == ["gate"] else print(json.dumps(build(), indent=1)))
