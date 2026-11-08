"""Extract: snapshot the current Hacker News top stories into an append-only CSV."""
import csv
import math
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

API = "https://hacker-news.firebaseio.com/v0"
RAW_PATH = os.path.join(os.path.dirname(__file__), "data", "raw_snapshots.csv")
FIELDS = ["snapshot_at", "rank", "story_id", "title", "url", "author", "score", "comments", "posted_at"]
TOP_N = 100
HTTP_ATTEMPTS = 3
HTTP_TIMEOUT = (5, 15)  # connect timeout, read inactivity timeout; not a total deadline
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_DELAY = 30


def fetch_json(path: str):
    """Retry transient GET failures only; malformed JSON and permanent HTTP errors fail closed."""
    for attempt in range(HTTP_ATTEMPTS):
        try:
            resp = requests.get(f"{API}/{path}.json", timeout=HTTP_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == HTTP_ATTEMPTS - 1:
                raise
            time.sleep(2 ** attempt)
            continue
        try:
            if resp.status_code in RETRY_STATUSES and attempt < HTTP_ATTEMPTS - 1:
                delay = 2 ** attempt
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        requested = float(retry_after)
                    except ValueError:
                        try:
                            requested = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            requested = 0
                    # Do not retry sooner than a long server-requested cooldown.
                    if not math.isfinite(requested) or requested > MAX_RETRY_DELAY:
                        resp.raise_for_status()
                    delay = max(delay, requested)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        finally:
            resp.close()
    raise RuntimeError("HTTP retry loop exhausted")  # defensive; final attempt raises or returns


def parse_item(item: dict, rank: int, snapshot_at: str) -> dict | None:
    """Turn a raw HN item into a flat row. Returns None for deleted/dead/non-story items."""
    if not item or item.get("type") != "story" or item.get("deleted") or item.get("dead"):
        return None
    return {
        "snapshot_at": snapshot_at,
        "rank": rank,
        "story_id": item["id"],
        "title": item.get("title", "").strip(),
        "url": item.get("url", ""),
        "author": item.get("by", ""),
        "score": item.get("score", 0),
        "comments": item.get("descendants", 0),
        "posted_at": datetime.fromtimestamp(item["time"], tz=timezone.utc).isoformat(),
    }


def extract(top_n: int = TOP_N) -> list[dict]:
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= TOP_N:
        raise ValueError(f"top_n must be an integer between 1 and {TOP_N}")
    snapshot_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ids = fetch_json("topstories")
    if not isinstance(ids, list):
        raise ValueError("The top-stories response must be a list of story IDs")
    ids = ids[:top_n]
    if any(type(story_id) is not int or story_id <= 0 for story_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("The top-stories response contains invalid or duplicate story IDs")
    with ThreadPoolExecutor(max_workers=16) as pool:
        items = list(pool.map(lambda i: fetch_json(f"item/{i}"), ids))
    rows = [parse_item(item, rank, snapshot_at) for rank, item in enumerate(items, start=1)]
    rows = [r for r in rows if r]
    # Match the dbt completeness gate before touching append-only history. An empty
    # run must not succeed merely because an older snapshot is still recent.
    minimum = math.ceil(top_n * 0.9)
    if len(rows) < minimum:
        raise ValueError(f"Incomplete snapshot: collected {len(rows)} stories; expected at least {minimum}")
    return rows


def append_snapshot(rows: list[dict], path: str = RAW_PATH) -> int:
    if not rows:
        raise ValueError("Cannot append an empty snapshot")
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    temporary = None
    try:
        # Keep incomplete writes out of history: a partial snapshot would keep
        # failing the historical dbt completeness check on every later run.
        with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8", dir=directory, delete=False) as fh:
            temporary = fh.name
            if not new_file:
                with open(path, newline="", encoding="utf-8") as previous:
                    shutil.copyfileobj(previous, fh)
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerows(rows)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return len(rows)


if __name__ == "__main__":
    n = append_snapshot(extract())
    print(f"Appended {n} rows to {RAW_PATH}")
