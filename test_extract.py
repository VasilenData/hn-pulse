from extract import parse_item

SNAP = "2026-01-01T00:00:00+00:00"


def test_parse_story():
    item = {"id": 1, "type": "story", "title": " Hello ", "url": "https://a.com/x", "by": "bob",
            "score": 10, "descendants": 3, "time": 1700000000}
    row = parse_item(item, 5, SNAP)
    assert row["title"] == "Hello" and row["rank"] == 5 and row["comments"] == 3
    assert row["posted_at"].startswith("2023-11-14")


def test_skips_dead_deleted_and_non_story():
    assert parse_item({"id": 2, "type": "story", "dead": True, "time": 1}, 1, SNAP) is None
    assert parse_item({"id": 3, "type": "story", "deleted": True, "time": 1}, 1, SNAP) is None
    assert parse_item({"id": 4, "type": "job", "time": 1}, 1, SNAP) is None
    assert parse_item(None, 1, SNAP) is None


def test_text_post_has_empty_url_and_zero_comments_default():
    row = parse_item({"id": 5, "type": "story", "title": "Ask HN", "time": 1700000000}, 2, SNAP)
    assert row["url"] == "" and row["comments"] == 0 and row["score"] == 0
