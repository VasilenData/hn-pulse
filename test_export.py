import json

import duckdb
import pytest

import export as exporter


@pytest.fixture
def mart_database(tmp_path):
    path = str(tmp_path / "marts.duckdb")
    with duckdb.connect(path) as con:
        con.execute("create table mart_daily_summary as select date '2026-01-02' as day, 2 as snapshots")
        con.execute("create table mart_top_domains as select 'example.com' as domain, 1 as stories, 2.0::double as avg_peak_score")
        con.execute("create table mart_hourly_activity as select 12 as posted_hour_utc, 2.0::double as avg_peak_score")
        con.execute("create table mart_front_page_now as select * from (values (2, 10), (1, 20)) t(rank, score)")
    return path


def test_export_orders_front_page_and_uses_selected_database(mart_database, tmp_path, monkeypatch):
    calls = []

    def build(**kwargs):
        calls.append(kwargs)
        return {"source": "selected database"}

    monkeypatch.setattr(exporter.quality, "build", build)
    output = tmp_path / "public" / "data.json"
    payload = exporter.export(mart_database, str(output))
    assert [row["rank"] for row in payload["mart_front_page_now"]] == [1, 2]
    assert calls == [{"db_path": mart_database}]
    assert json.loads(output.read_text()) == payload
    assert list(output.parent.iterdir()) == [output]


def test_failed_serialization_preserves_previous_export(mart_database, tmp_path, monkeypatch):
    output = tmp_path / "data.json"
    previous = '{"previous": "complete export"}'
    output.write_text(previous)
    monkeypatch.setattr(exporter.quality, "build", lambda **kwargs: {})

    def interrupted_dump(payload, stream, **kwargs):
        stream.write('{"partial":')
        raise OSError("simulated disk write failure")

    monkeypatch.setattr(exporter.json, "dump", interrupted_dump)
    with pytest.raises(OSError, match="disk write failure"):
        exporter.export(mart_database, str(output))
    assert output.read_text() == previous
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data.json", "marts.duckdb"]


def test_nonfinite_metric_cannot_replace_valid_json(mart_database, tmp_path, monkeypatch):
    with duckdb.connect(mart_database) as con:
        con.execute("update mart_hourly_activity set avg_peak_score = 'NaN'::double")
    output = tmp_path / "data.json"
    output.write_text('{}')
    monkeypatch.setattr(exporter.quality, "build", lambda **kwargs: {})
    with pytest.raises(ValueError):
        exporter.export(mart_database, str(output))
    assert output.read_text() == '{}'
