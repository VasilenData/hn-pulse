"""Export: read the dbt marts from DuckDB and write the JSON that powers the dashboard."""
import json
import os
from datetime import datetime, timezone

import duckdb

ROOT = os.path.dirname(__file__)
DB_PATH = os.path.join(ROOT, "target", "hn_pulse.duckdb")
OUT_PATH = os.path.join(ROOT, "docs", "data.json")
MARTS = ["mart_daily_summary", "mart_top_domains", "mart_hourly_activity", "mart_front_page_now"]


def export(db_path: str = DB_PATH, out_path: str = OUT_PATH) -> dict:
    con = duckdb.connect(db_path, read_only=True)
    payload = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    for mart in MARTS:
        cur = con.execute(f"select * from {mart}")
        cols = [c[0] for c in cur.description]
        payload[mart] = [
            {c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, row)}
            for row in cur.fetchall()
        ]
    con.close()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    return payload


if __name__ == "__main__":
    data = export()
    print({k: len(v) for k, v in data.items() if isinstance(v, list)})
