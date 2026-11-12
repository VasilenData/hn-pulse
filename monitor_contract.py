"""Validate the public dashboard contract without importing dbt or DuckDB."""
import math
from datetime import date


def count(value):
    return type(value) is int and value >= 0


def metric(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_export(data):
    """Reject a fresh timestamp wrapped around missing, partial or failed output.

    These are independent consumer checks, not a rerun of the source/dbt tests.
    The latest front-page mart intentionally contains at most 30 stories.
    """
    if not isinstance(data, dict):
        raise ValueError("export must be an object")
    validators = {
        "mart_daily_summary": lambda r: isinstance(r.get("day"), str)
        and bool(date.fromisoformat(r["day"])) and count(r.get("snapshots")),
        "mart_front_page_now": lambda r: count(r.get("rank")) and r["rank"] > 0
        and count(r.get("story_id")) and r["story_id"] > 0
        and metric(r.get("score")) and count(r.get("comments"))
        and (r.get("title") is None or isinstance(r["title"], str))
        and isinstance(r.get("domain"), str),
        "mart_top_domains": lambda r: isinstance(r.get("domain"), str) and count(r.get("stories")),
        "mart_hourly_activity": lambda r: count(r.get("posted_hour_utc"))
        and r["posted_hour_utc"] < 24 and metric(r.get("avg_peak_score")),
    }
    for name, valid in validators.items():
        rows = data.get(name)
        if not isinstance(rows, list) or (not rows and name != "mart_top_domains") or not all(isinstance(r, dict) and valid(r) for r in rows):
            raise ValueError(f"missing, empty or invalid {name}")
    front = data["mart_front_page_now"]
    if len(front) != 30 or len({r["story_id"] for r in front}) != len(front):
        raise ValueError("invalid front-page story grain")
    if len({r["rank"] for r in front}) != len(front) or max(r["rank"] for r in front) > 100:
        raise ValueError("invalid front-page ranks")
    for name, key in (("mart_daily_summary", "day"), ("mart_top_domains", "domain"),
                      ("mart_hourly_activity", "posted_hour_utc")):
        if len({r[key] for r in data[name]}) != len(data[name]):
            raise ValueError(f"invalid {name} grain")
    q = data.get("quality")
    if not isinstance(q, dict):
        raise ValueError("missing quality report")
    try:
        tests, models, rows = q["tests"], q["models"], q["rows"]
        values = [tests[k] for k in ("pass", "warn", "fail", "error")]
        values += [models[k] for k in ("success", "error")]
        values += [q["models_total"], q["contracts_enforced"], rows["fct_stories"], rows["stg_snapshots"]]
        if not all(count(v) for v in values):
            raise ValueError("invalid health counts")
        if tests["fail"] or tests["error"] or models["error"]:
            raise ValueError("published build contains failed results")
        if tests["pass"] + tests["warn"] == 0:
            raise ValueError("no completed data tests")
        if not q["models_total"] or models["success"] != q["models_total"] or q["contracts_enforced"] != q["models_total"]:
            raise ValueError("incomplete model or contract coverage")
        if not rows["fct_stories"] or rows["stg_snapshots"] < rows["fct_stories"]:
            raise ValueError("invalid source/fact counts")
    except (KeyError, TypeError) as error:
        raise ValueError("missing health fields") from error
    return data
