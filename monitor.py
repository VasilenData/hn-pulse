"""Observe the published Pages export independently of extraction and dbt.

No credentials, messages, repository writes or claimed uptime. A failed observation
is unavailable, not proof that publication stopped. GitHub scheduling can be delayed.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_URL = "https://vasilendata.github.io/hn-pulse/data.json"


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def assess(payload, now=None, max_age_hours=6):
    now = now or datetime.now(timezone.utc)
    report = {"checked_at": now.isoformat(), "max_age_hours": max_age_hours}
    try:
        generated = timestamp(payload["generated_at"])
        newest = timestamp(payload["quality"]["newest_snapshot_at"])
        ages = {"publication_age_hours": (now - generated).total_seconds() / 3600,
                "source_age_hours": (now - newest).total_seconds() / 3600}
        if min(ages.values()) < -5 / 60:
            raise ValueError("timestamp is more than five minutes in the future")
        report.update(ages)
        report.update(generated_at=generated.isoformat(), newest_snapshot_at=newest.isoformat())
        report["status"] = "overdue" if max(ages.values()) > max_age_hours else "fresh"
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        report.update(status="unavailable", reason=f"Invalid publication timestamps: {error}")
    return report


def observe(url=DEFAULT_URL, now=None):
    try:
        with requests.get(url, timeout=(5, 15), headers={"Cache-Control": "no-cache"}) as response:
            response.raise_for_status()
            report = assess(response.json(), now=now)
    except (requests.RequestException, ValueError) as error:
        report = {"checked_at": (now or datetime.now(timezone.utc)).isoformat(),
                  "status": "unavailable", "reason": f"Could not observe published export: {type(error).__name__}"}
    report["url"] = url
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=Path("monitor-status.json"))
    args = parser.parse_args()
    report = observe(args.url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["status"] == "fresh" else 1


if __name__ == "__main__":
    raise SystemExit(main())
