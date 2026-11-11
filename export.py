"""Export: read the dbt marts from DuckDB and write the JSON that powers the dashboard."""
import json
import os
import tempfile
from datetime import datetime, timezone

import duckdb

import quality

ROOT = os.path.dirname(__file__)
DB_PATH = os.path.join(ROOT, "target", "hn_pulse.duckdb")
OUT_PATH = os.path.join(ROOT, "docs", "data.json")
MARTS = ["mart_daily_summary", "mart_top_domains", "mart_hourly_activity", "mart_front_page_now"]


def export(db_path: str = DB_PATH, out_path: str = OUT_PATH) -> dict:
    payload = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    ordering = ["day", "stories desc, avg_peak_score desc, domain", "posted_hour_utc", "rank"]
    with duckdb.connect(db_path, read_only=True) as con:
        for mart, order in zip(MARTS, ordering):
            cur = con.execute(f"select * from {mart} order by {order}")
            cols = [c[0] for c in cur.description]
            payload[mart] = [
                {c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, row)}
                for row in cur.fetchall()
            ]
    # Direct CLI calls must honor the same publication gate as orchestration.
    # Missing health artifacts or a partial/failed dbt build cannot look fresh.
    payload["quality"] = quality.build(db_path=db_path)
    quality.assert_publishable(payload["quality"])
    directory = os.path.dirname(out_path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        # A reader sees either the previous complete export or the new one.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as fh:
            temporary = fh.name
            json.dump(payload, fh, indent=1, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, out_path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return payload


if __name__ == "__main__":
    data = export()
    print({k: len(v) for k, v in data.items() if isinstance(v, list)})
