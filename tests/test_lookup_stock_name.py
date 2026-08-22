"""Tests for tools/lookup_stock_name.py (pure code↔name cache, no AI)."""

import json

import pytest

import tools.lookup_stock_name as lsn


@pytest.fixture
def temp_names_file(tmp_path, monkeypatch):
    """Redirect the cache file to a temp path for isolation."""
    f = tmp_path / "stock_names.json"
    monkeypatch.setattr(lsn, "NAMES_FILE", f)
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
