import csv

import pytest

import extract as extractor
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


@pytest.mark.parametrize("response", [[], [1], [1, 1], None, "invalid", [True], [-1]])
def test_rejects_empty_partial_or_invalid_top_stories(monkeypatch, response):
    def fetch(path):
        return response if path == "topstories" else {"id": 1, "type": "story", "time": 1}

    monkeypatch.setattr(extractor, "fetch_json", fetch)
    with pytest.raises(ValueError):
        extractor.extract()


def test_rejects_snapshot_when_too_many_items_are_deleted(monkeypatch):
    monkeypatch.setattr(extractor, "fetch_json", lambda path: list(range(1, 101)) if path == "topstories" else None)
    with pytest.raises(ValueError, match="Incomplete snapshot"):
        extractor.extract()


def test_extract_preserves_api_rank_when_deleted_items_are_skipped(monkeypatch):
    def fetch(path):
        if path == "topstories":
            return list(range(1, 11))
        story_id = int(path.split("/")[1])
        return None if story_id == 2 else {"id": story_id, "type": "story", "time": 1}

    monkeypatch.setattr(extractor, "fetch_json", fetch)
    rows = extractor.extract(top_n=10)
    assert [row["rank"] for row in rows] == [1, 3, 4, 5, 6, 7, 8, 9, 10]
    assert len({row["snapshot_at"] for row in rows}) == 1


def test_empty_append_leaves_existing_history_untouched(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.write_text("existing history\n")
    with pytest.raises(ValueError, match="empty snapshot"):
        extractor.append_snapshot([], str(raw))
    assert raw.read_text() == "existing history\n"


def test_append_to_empty_file_adds_header(tmp_path):
    raw = tmp_path / "raw.csv"
    raw.touch()
    row = parse_item({"id": 5, "type": "story", "time": 1}, 1, SNAP)
    assert extractor.append_snapshot([row], str(raw)) == 1
    with raw.open(newline="", encoding="utf-8") as stream:
        assert list(csv.DictReader(stream))[0]["story_id"] == "5"


def test_failed_append_preserves_complete_history(tmp_path, monkeypatch):
    raw = tmp_path / "raw.csv"
    row = parse_item({"id": 5, "type": "story", "time": 1}, 1, SNAP)
    extractor.append_snapshot([row], str(raw))
    previous = raw.read_bytes()

    def interrupted_rows(writer, rows):
        writer.writerow(rows[0])
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(csv.DictWriter, "writerows", interrupted_rows)
    with pytest.raises(OSError, match="disk write failure"):
        extractor.append_snapshot([row], str(raw))
    assert raw.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [raw]


def test_append_preserves_prior_rows_and_one_header(tmp_path):
    raw = tmp_path / "raw.csv"
    first = parse_item({"id": 5, "type": "story", "time": 1}, 1, SNAP)
    second = parse_item({"id": 6, "type": "story", "time": 1}, 2, SNAP)
    extractor.append_snapshot([first], str(raw))
    extractor.append_snapshot([second], str(raw))
    with raw.open(newline="", encoding="utf-8") as stream:
        assert [row["story_id"] for row in csv.DictReader(stream)] == ["5", "6"]
