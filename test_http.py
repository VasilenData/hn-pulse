from unittest.mock import Mock

import pytest
import requests

import extract


def response(code=200, headers=None):
    result = Mock(status_code=code, headers=headers or {})
    result.json.return_value = {"id": 1}
    if code >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(str(code))
    return result


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(), response(503)])
def test_transient_failure_recovers_with_bounded_timeout(monkeypatch, failure):
    success = response()
    get = Mock(side_effect=[failure, success])
    sleep = Mock()
    monkeypatch.setattr(extract.requests, "get", get)
    monkeypatch.setattr(extract.time, "sleep", sleep)
    assert extract.fetch_json("item/1") == {"id": 1}
    assert get.call_count == 2
    assert get.call_args.kwargs["timeout"] == (5, 15)
    sleep.assert_called_once_with(1)
    success.close.assert_called_once()


def test_retry_exhaustion_fails_instead_of_returning_empty_data(monkeypatch):
    get = Mock(side_effect=requests.Timeout())
    sleep = Mock()
    monkeypatch.setattr(extract.requests, "get", get)
    monkeypatch.setattr(extract.time, "sleep", sleep)
    with pytest.raises(requests.Timeout):
        extract.fetch_json("topstories")
    assert get.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_permanent_failure_is_not_retried(monkeypatch, code):
    get = Mock(return_value=response(code))
    monkeypatch.setattr(extract.requests, "get", get)
    with pytest.raises(requests.HTTPError):
        extract.fetch_json("topstories")
    assert get.call_count == 1


def test_retry_after_respected_and_long_cooldown_fails_closed(monkeypatch):
    get = Mock(side_effect=[response(429, {"Retry-After": "4"}), response()])
    sleep = Mock()
    monkeypatch.setattr(extract.requests, "get", get)
    monkeypatch.setattr(extract.time, "sleep", sleep)
    extract.fetch_json("topstories")
    sleep.assert_called_once_with(4)
    get.side_effect = None
    get.return_value = response(429, {"Retry-After": "3600"})
    get.reset_mock()
    with pytest.raises(requests.HTTPError):
        extract.fetch_json("topstories")
    assert get.call_count == 1


def test_invalid_json_is_not_retried(monkeypatch):
    bad = response()
    bad.json.side_effect = ValueError("invalid JSON")
    get = Mock(return_value=bad)
    monkeypatch.setattr(extract.requests, "get", get)
    with pytest.raises(ValueError, match="invalid JSON"):
        extract.fetch_json("topstories")
    assert get.call_count == 1
    bad.close.assert_called_once()
