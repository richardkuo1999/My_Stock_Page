from __future__ import annotations

import pytest
from sqlmodel import SQLModel, create_engine

from analysis_bot.services.uanalyze_monitor import (
    _format_report,
    _load_last_id,
    _save_last_id,
    check_new_reports,
)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Provide an isolated SQLite DB with all tables created."""
    import analysis_bot.database as database
    from analysis_bot.models.config import SystemConfig  # noqa: F401
    from analysis_bot.models.subscriber import Subscriber  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    return engine


# --- state management ---

def test_load_last_id_no_row(isolated_db) -> None:
    assert _load_last_id() == 0


def test_save_and_load_last_id(isolated_db) -> None:
    _save_last_id(42)
    assert _load_last_id() == 42


def test_save_overwrites(isolated_db) -> None:
    _save_last_id(10)
    _save_last_id(20)
    assert _load_last_id() == 20


# --- format ---

def test_format_report_basic() -> None:
    report = {
        "name": "元大投信",
        "stock_name": "台積電",
        "content_date": "2026-04-20T12:00:00",
        "summary": "營收創新高",
    }
    text, has_kw = _format_report(report, 1, 5, [])
    assert "[1/5]" in text
    assert "元大投信" in text
    assert "台積電" in text
    assert "營收創新高" in text
    assert has_kw is False


def test_format_report_keyword_highlight() -> None:
    report = {
        "name": "元大投信",
        "stock_name": "台積電",
        "content_date": "2026-04-20",
        "summary": "台積電營收",
    }
    text, has_kw = _format_report(report, 1, 1, ["台積電"])
    assert "<b>台積電</b>" in text
    assert has_kw is True


def test_format_report_no_keyword_match() -> None:
    report = {
        "name": "報告",
        "stock_name": "聯發科",
        "content_date": "2026-04-20",
        "summary": "內容",
    }
    _, has_kw = _format_report(report, 1, 1, ["台積電"])
    assert has_kw is False


# --- check_new_reports ---

@pytest.mark.asyncio
async def test_check_new_reports_no_url(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """When UANALYZE_API_URL is empty, should return 0."""
    import analysis_bot.services.uanalyze_monitor as mod

    class FakeSettings:
        UANALYZE_API_URL = ""

    monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())
    result = await check_new_reports()
    assert result == 0


@pytest.mark.asyncio
async def test_check_new_reports_first_run_saves_state(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """First run (last_id=0) should save state but not send messages."""
    import analysis_bot.services.uanalyze_monitor as mod

    class FakeSettings:
        UANALYZE_API_URL = "http://fake/api"
        UANALYZE_KEYWORDS = ""

    monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())

    reports = [{"id": 10, "name": "R1", "stock_name": "S1", "content_date": "2026-01-01", "summary": "s"}]

    class FakeResp:
        status = 200
        async def json(self):
            return {"data": {"data": reports}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass

    class FakeSession:
        def get(self, *a, **kw):
            return FakeResp()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass

    monkeypatch.setattr(mod, "create_session", lambda **kw: FakeSession())

    result = await check_new_reports()
    assert result == 0  # first run, no push
    assert _load_last_id() == 10
