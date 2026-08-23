"""Tests for tools/lookup_stock_name.py (pure code↔name cache, no AI)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tools.lookup_stock_name as lsn


@pytest.fixture
def temp_names_file(tmp_path, monkeypatch):
    """Redirect the cache file (and its meta) to a temp path for isolation."""
    f = tmp_path / "stock_names.json"
    monkeypatch.setattr(lsn, "NAMES_FILE", f)
    monkeypatch.setattr(lsn, "META_FILE", tmp_path / "stock_names_meta.json")
    return f


def test_load_bootstraps_from_seed(temp_names_file):
    """First load with no file writes the seed and returns it."""
    names = lsn.load_names()
    assert names["2330"] == "台積電"
    assert temp_names_file.exists()  # bootstrapped to disk


def test_get_name_hit_and_miss(temp_names_file):
    assert lsn.get_name("2330") == "台積電"  # seeded
    assert lsn.get_name("9999") is None  # unknown


def test_set_name_writes_back(temp_names_file):
    """set_name persists and subsequent get_name hits the cache."""
    assert lsn.get_name("9999") is None
    lsn.set_name("9999", "測試公司")
    assert lsn.get_name("9999") == "測試公司"
    # Confirm it is actually on disk
    on_disk = json.loads(temp_names_file.read_text(encoding="utf-8"))
    assert on_disk["9999"] == "測試公司"


def test_corrupt_file_falls_back_to_seed(temp_names_file):
    """A corrupt cache file is replaced by the seed rather than crashing."""
    temp_names_file.write_text("{ not valid json", encoding="utf-8")
    names = lsn.load_names()
    assert names["2330"] == "台積電"


def test_no_ai_import():
    """The tool must not import the agent bridge — it is pure data, no AI."""
    import inspect

    src = inspect.getsource(lsn)
    assert "agent.bridge" not in src
    assert "AntigravityCLIBridge" not in src


# --- StockPool fetch / refresh ------------------------------------------------


def _mock_httpx_client(response):
    """Build a mock httpx.AsyncClient that returns `response` on get()."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value={"data": data})
    return resp


@pytest.mark.asyncio
async def test_fetch_stock_pool_returns_dict():
    """fetch_stock_pool parses StockPool list into a code→name dict."""
    data = [
        {"stock_code": "1101", "stock_name": "台泥", "country": "TW"},
        {"stock_code": "2330", "stock_name": "台積電", "country": "TW"},
        {"stock_code": "", "stock_name": "無代號"},  # skipped
    ]
    client = _mock_httpx_client(_mock_response(200, data))
    with patch("httpx.AsyncClient", return_value=client):
        pool = await lsn.fetch_stock_pool()
    assert pool == {"1101": "台泥", "2330": "台積電"}


@pytest.mark.asyncio
async def test_fetch_stock_pool_http_error_returns_empty():
    client = _mock_httpx_client(_mock_response(500, None))
    with patch("httpx.AsyncClient", return_value=client):
        pool = await lsn.fetch_stock_pool()
    assert pool == {}


@pytest.mark.asyncio
async def test_refresh_pool_merges_without_clobbering_manual_set(temp_names_file):
    """StockPool is authoritative, but a user's manual --set-only code survives."""
    # User manually set a code that StockPool does NOT cover.
    lsn.set_name("9999", "自訂公司")
    # ...and one that StockPool DOES cover with a different name.
    lsn.set_name("2330", "舊名")

    pool = {"2330": "台積電", "1101": "台泥"}
    with patch.object(lsn, "fetch_stock_pool", AsyncMock(return_value=pool)):
        count = await lsn.refresh_pool(force=True)

    names = lsn.load_names()
    assert names["9999"] == "自訂公司"      # manual-only key preserved
    assert names["2330"] == "台積電"        # pool wins for covered codes
    assert names["1101"] == "台泥"          # new pool entry added
    assert count == len(names)


@pytest.mark.asyncio
async def test_refresh_pool_skips_when_fresh(temp_names_file):
    """Non-force refresh is a no-op while the table is fresh."""
    lsn.save_names({"2330": "台積電"})
    lsn._save_meta({"refreshed_at": time.time()})  # just refreshed
    fetch = AsyncMock(return_value={"1101": "台泥"})
    with patch.object(lsn, "fetch_stock_pool", fetch):
        count = await lsn.refresh_pool(force=False)
    assert count == 0
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_pool_runs_when_stale(temp_names_file):
    """Non-force refresh runs when the table is older than the TTL."""
    lsn.save_names({"2330": "台積電"})
    lsn._save_meta({"refreshed_at": time.time() - (8 * 24 * 3600)})  # >7 days
    with patch.object(lsn, "fetch_stock_pool", AsyncMock(return_value={"1101": "台泥"})):
        count = await lsn.refresh_pool(force=False)
    assert count > 0
    assert lsn.get_name("1101") == "台泥"


@pytest.mark.asyncio
async def test_refresh_pool_empty_pool_keeps_existing(temp_names_file):
    """A failed (empty) fetch must NOT wipe the existing table (graceful degrade)."""
    lsn.save_names({"2330": "台積電", "9999": "自訂"})
    with patch.object(lsn, "fetch_stock_pool", AsyncMock(return_value={})):
        count = await lsn.refresh_pool(force=True)
    assert count == 0
    names = lsn.load_names()
    assert names["2330"] == "台積電"
    assert names["9999"] == "自訂"
