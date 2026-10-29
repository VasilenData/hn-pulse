"""Extract: snapshot the current Hacker News top stories into an append-only CSV."""
import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

API = "https://hacker-news.firebaseio.com/v0"
RAW_PATH = os.path.join(os.path.dirname(__file__), "data", "raw_snapshots.csv")
FIELDS = ["snapshot_at", "rank", "story_id", "title", "url", "author", "score", "comments", "posted_at"]
TOP_N = 100


def fetch_json(path: str):
    resp = requests.get(f"{API}/{path}.json", timeout=15)
    resp.raise_for_status()
    return resp.json()


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
    snapshot_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ids = fetch_json("topstories")[:top_n]
    with ThreadPoolExecutor(max_workers=16) as pool:
        items = list(pool.map(lambda i: fetch_json(f"item/{i}"), ids))
    rows = [parse_item(item, rank, snapshot_at) for rank, item in enumerate(items, start=1)]
    return [r for r in rows if r]


def append_snapshot(rows: list[dict], path: str = RAW_PATH) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    n = append_snapshot(extract())
    print(f"Appended {n} rows to {RAW_PATH}")
