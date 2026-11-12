import pytest

from lineage import impact


def test_impact_includes_downstream_tests_and_consumers_but_not_other_branch():
    manifest = {"nodes": {
        "model.source": {"resource_type": "model", "name": "source", "columns": {"score": {}}, "depends_on": {"nodes": []}},
        "model.mart": {"resource_type": "model", "name": "mart", "depends_on": {"nodes": ["model.source"]}},
        "model.other": {"resource_type": "model", "name": "other", "depends_on": {"nodes": []}},
        "test.mart": {"resource_type": "test", "name": "mart_key", "depends_on": {"nodes": ["model.mart"]}},
    }, "exposures": {
        "exposure.dashboard": {"resource_type": "exposure", "name": "dashboard", "url": "https://example.test/",
                               "owner": {"name": "owner"}, "depends_on": {"nodes": ["model.mart"]}}
    }}
    result = impact(manifest, "source", "score")
    assert result["models"] == ["mart", "source"]
    assert result["tests"] == ["mart_key"]
    assert result["consumers"] == [{"name": "dashboard", "url": "https://example.test/", "owner": {"name": "owner"}}]
    assert "model-level" in result["granularity"]
    with pytest.raises(ValueError, match="Column"):
        impact(manifest, "source", "invented")
    with pytest.raises(ValueError, match="model"):
        impact(manifest, "missing")
