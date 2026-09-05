"""Tests for tools/finmind.py."""

from unittest.mock import MagicMock, patch

from tools import finmind
from tools.finmind import _get_tokens, fetch_dataset, fetch_info, fetch_per_pbr


def _mock_client(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    client = MagicMock()
    client.get.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def test_get_tokens_json_array(monkeypatch):
    monkeypatch.setenv("FINMIND_TOKENS", '["tok1","tok2"]')
    assert _get_tokens() == ["tok1", "tok2"]


def test_get_tokens_single(monkeypatch):
    monkeypatch.setenv("FINMIND_TOKENS", "plain_token")
    assert _get_tokens() == ["plain_token"]


def test_get_tokens_empty(monkeypatch):
    monkeypatch.setenv("FINMIND_TOKENS", "")
    assert _get_tokens() == []


def test_fetch_dataset_success():
    payload = {"status": 200, "msg": "success", "data": [
        {"date": "2026-09-04", "stock_id": "2330", "PER": 27.94, "PBR": 9.72, "dividend_yield": 0.91},
    ]}
    with patch("httpx.Client", return_value=_mock_client(payload)):
        res = fetch_dataset("TaiwanStockPER", "2330", "2025-01-01")
    assert res["dataset"] == "TaiwanStockPER"
    assert res["data_id"] == "2330"
    assert res["data"][0]["PER"] == 27.94


def test_fetch_dataset_api_error():
    payload = {"status": 402, "msg": "Please login"}
    with patch("httpx.Client", return_value=_mock_client(payload)):
        # status!=200 in payload → error（但 HTTP 200）
        res = fetch_dataset("TaiwanStockPER", "2330")
    assert "error" in res


def test_fetch_dataset_http_error():
    with patch("httpx.Client", return_value=_mock_client({}, status=500)):
        res = fetch_dataset("TaiwanStockPER", "2330")
    assert "error" in res
    assert "500" in res["error"]


def test_fetch_per_pbr_uses_dataset():
    payload = {"status": 200, "data": [{"PER": 15.0, "PBR": 2.0}]}
    with patch("httpx.Client", return_value=_mock_client(payload)):
        res = fetch_per_pbr("2330")
    assert res["dataset"] == "TaiwanStockPER"


def test_fetch_info_no_start_date():
    payload = {"status": 200, "data": [{"stock_name": "台積電", "industry_category": "半導體"}]}
    captured = {}

    def _capture_client(*args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        client = MagicMock()

        def _get(url, params=None):
            captured["params"] = params
            return resp

        client.get.side_effect = _get
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    with patch("httpx.Client", side_effect=_capture_client):
        res = fetch_info("2330")
    assert res["dataset"] == "TaiwanStockInfo"
    assert "start_date" not in captured["params"]  # info 不帶 start_date
