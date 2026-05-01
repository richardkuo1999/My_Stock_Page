"""Tests for Google Sheets watchlist sync."""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from analysis_bot.bot import handlers
from analysis_bot.models.gsheet_sub import GSheetSubscription
from analysis_bot.models.watchlist import WatchlistEntry
from analysis_bot.services.gsheet_monitor import (
    _hash_content,
    _parse_rows,
    _parse_sheet_url,
    _sync_watchlist,
    gsheet_sync_for_user,
)
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate


# --- Fixtures ---


@pytest.fixture()
def gsheet_engine(tmp_path, monkeypatch):
    db_path = tmp_path / "gsheet_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    import analysis_bot.database as database
    import analysis_bot.services.gsheet_monitor as gsheet_mod

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(handlers, "engine", engine)
    monkeypatch.setattr(gsheet_mod, "engine", engine)
    return engine


SAMPLE_CSV = """\
,短線持股%,40,更新日期,2026/04/28,,,,,,,,
,股票代號,股票名稱,新增日期,狀態,週期,備註&策略,現價,參考損,月成本,持倉%,近期動作
,3324,雙鴻,2026/03/24,放飛,波段,波段 CB 1100,"1,140.0","900.0",,★☆☆☆☆,
,2382,廣達,2026/04/09,持有,波段,,"312.5","280.0",,★☆☆☆☆,
,3680,家登,2026/04/20,持有,波段,問就是會漲,"537.0","437.0",,★★★★★,再再再加碼
"""

SAMPLE_CSV_UPDATED = """\
,短線持股%,40,更新日期,2026/04/29,,,,,,,,
,股票代號,股票名稱,新增日期,狀態,週期,備註&策略,現價,參考損,月成本,持倉%,近期動作
,2382,廣達,2026/04/09,持有,波段,加碼,"320.0","280.0",,★★☆☆☆,加碼
,3680,家登,2026/04/20,持有,波段,問就是會漲,"537.0","437.0",,★★★★★,再再再加碼
,6679,鈺太,2026/04/09,放飛,波段,波段,"286.0","250.0",,★★☆☆☆,
"""

TEST_GSHEET_URL = "https://docs.google.com/spreadsheets/d/abc123/edit?gid=0#gid=0"


@pytest.fixture()
def mock_fetch(monkeypatch):
    """Mock fetch_sheet_csv to return SAMPLE_CSV for any request."""
    import analysis_bot.services.gsheet_monitor as gsheet_mod

    async def _fake_fetch(spreadsheet_id: str, gid: str) -> str | None:
        return SAMPLE_CSV

    monkeypatch.setattr(gsheet_mod, "fetch_sheet_csv", _fake_fetch)
    # Also patch in handlers since it imports directly
    return _fake_fetch


# --- Unit Tests: URL parsing ---


def test_parse_sheet_url_basic():
    url = "https://docs.google.com/spreadsheets/d/1EP56B6XBGzvXowFnd5dtTJhGSbhcRzb42rUfke5mfSM/edit?gid=192739703#gid=192739703"
    sheet_id, gid = _parse_sheet_url(url)
    assert sheet_id == "1EP56B6XBGzvXowFnd5dtTJhGSbhcRzb42rUfke5mfSM"
    assert gid == "192739703"


def test_parse_sheet_url_no_gid():
    url = "https://docs.google.com/spreadsheets/d/abc123/edit"
    sheet_id, gid = _parse_sheet_url(url)
    assert sheet_id == "abc123"
    assert gid == "0"


def test_parse_sheet_url_invalid():
    with pytest.raises(ValueError):
        _parse_sheet_url("https://example.com/not-a-sheet")


# --- Unit Tests: CSV parsing ---


def test_parse_rows_basic():
    entries = _parse_rows(SAMPLE_CSV)
    assert len(entries) == 3

    # First entry
    assert entries[0]["ticker"] == "3324"
    assert entries[0]["name"] == "雙鴻"
    assert entries[0]["price"] == 1140.0
    assert "狀態:放飛" in entries[0]["note"]
    assert "策略:波段 CB 1100" in entries[0]["note"]
    assert "停損:900.0" in entries[0]["note"]

    # Third entry with recent_action
    assert entries[2]["ticker"] == "3680"
    assert "動作:再再再加碼" in entries[2]["note"]


def test_parse_rows_skips_invalid():
    csv_text = """\
,header row,,,,,,,,,,
,股票代號,股票名稱,新增日期,狀態,週期,備註,現價,參考損,月成本,持倉%,近期動作
,not_a_ticker,test,,,,,,,,,
,2330,台積電,2026/01/01,持有,波段,,600.0,500.0,,★★★☆☆,
"""
    entries = _parse_rows(csv_text)
    assert len(entries) == 1
    assert entries[0]["ticker"] == "2330"


def test_parse_rows_empty():
    entries = _parse_rows("")
    assert entries == []


# --- Unit Tests: hash ---


def test_hash_content():
    h1 = _hash_content("hello")
    h2 = _hash_content("hello")
    h3 = _hash_content("world")
    assert h1 == h2
    assert h1 != h3


# --- Integration Tests: sync watchlist ---


def test_sync_watchlist_add(gsheet_engine):
    entries = _parse_rows(SAMPLE_CSV)
    added, updated, removed = _sync_watchlist(
        chat_id=1, user_id=10, entries=entries, source_url="http://test"
    )

    assert {e["ticker"] for e in added} == {"3324", "2382", "3680"}
    assert updated == []
    assert removed == []

    # Verify DB
    with Session(gsheet_engine) as session:
        rows = session.exec(select(WatchlistEntry)).all()
        assert len(rows) == 3
        tickers = {r.ticker for r in rows}
        assert tickers == {"3324", "2382", "3680"}
        # Check source is set
        for r in rows:
            assert r.source == "gsheet"


def test_sync_watchlist_update(gsheet_engine):
    # Initial sync
    entries1 = _parse_rows(SAMPLE_CSV)
    _sync_watchlist(chat_id=1, user_id=10, entries=entries1, source_url="http://test")

    # Updated sync
    entries2 = _parse_rows(SAMPLE_CSV_UPDATED)
    added, updated, removed = _sync_watchlist(
        chat_id=1, user_id=10, entries=entries2, source_url="http://test"
    )

    assert {e["ticker"] for e in added} == {"6679"}
    assert "2382" in {e["ticker"] for e in updated}  # note/price changed
    assert set(removed) == {"3324"}  # removed from sheet

    # Verify DB state
    with Session(gsheet_engine) as session:
        rows = session.exec(select(WatchlistEntry)).all()
        tickers = {r.ticker for r in rows}
        assert tickers == {"2382", "3680", "6679"}
        # 3324 should be gone
        assert "3324" not in tickers


def test_sync_watchlist_removes_manual_entry(gsheet_engine):
    """If user manually added a ticker and sheet doesn't have it, it gets removed."""
    # Manually add a ticker
    with Session(gsheet_engine) as session:
        session.add(WatchlistEntry(
            chat_id=1, user_id=10, ticker="9999",
            alias="手動加的", source="manual",
        ))
        session.commit()

    # Sync with sheet that doesn't have 9999
    entries = _parse_rows(SAMPLE_CSV)
    added, updated, removed = _sync_watchlist(
        chat_id=1, user_id=10, entries=entries, source_url="http://test"
    )

    assert "9999" in removed

    with Session(gsheet_engine) as session:
        rows = session.exec(select(WatchlistEntry)).all()
        tickers = {r.ticker for r in rows}
        assert "9999" not in tickers


def test_sync_watchlist_overwrites_manual_entry(gsheet_engine):
    """If user manually added a ticker and sheet also has it, sheet data wins."""
    # Manually add
    with Session(gsheet_engine) as session:
        session.add(WatchlistEntry(
            chat_id=1, user_id=10, ticker="2382",
            alias="我自己加的", note="我的備註", source="manual",
        ))
        session.commit()

    # Sync — sheet has 2382 with different data
    entries = _parse_rows(SAMPLE_CSV)
    added, updated, removed = _sync_watchlist(
        chat_id=1, user_id=10, entries=entries, source_url="http://test"
    )

    assert "2382" in {e["ticker"] for e in updated}

    with Session(gsheet_engine) as session:
        row = session.exec(
            select(WatchlistEntry).where(WatchlistEntry.ticker == "2382")
        ).first()
        assert row.alias == "廣達"  # overwritten by sheet
        assert row.source == "gsheet"  # source updated
        assert "狀態:持有" in row.note  # sheet note


# --- Bot Command Tests ---


@pytest.mark.asyncio
async def test_gsheet_command_no_args(gsheet_engine):
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=[]))
    assert "用法" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_add_invalid_url(gsheet_engine, mock_fetch):
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=["add", "https://example.com"]))
    assert "❌" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_add_success(gsheet_engine, mock_fetch):
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=["add", TEST_GSHEET_URL, "我的持股"]))
    assert "✅" in msg.reply_text_calls[0].text
    assert "我的持股" in msg.reply_text_calls[0].text

    # Verify DB
    with Session(gsheet_engine) as session:
        row = session.exec(select(GSheetSubscription)).first()
        assert row is not None
        assert row.url == TEST_GSHEET_URL
        assert row.label == "我的持股"
        assert row.chat_id == 1
        assert row.user_id == 10


@pytest.mark.asyncio
async def test_gsheet_add_duplicate(gsheet_engine, mock_fetch):
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update1, FakeContext(args=["add", TEST_GSHEET_URL]))

    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update2, FakeContext(args=["add", TEST_GSHEET_URL]))
    assert "已註冊過" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_add_unreachable(gsheet_engine, monkeypatch):
    """URL format is valid but sheet is not accessible."""
    import analysis_bot.services.gsheet_monitor as gsheet_mod

    async def _fail_fetch(spreadsheet_id, gid):
        return None

    monkeypatch.setattr(gsheet_mod, "fetch_sheet_csv", _fail_fetch)

    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=["add", TEST_GSHEET_URL]))
    assert "無法存取" in msg.reply_text_calls[0].text

    # Should NOT be saved to DB
    with Session(gsheet_engine) as session:
        row = session.exec(select(GSheetSubscription)).first()
        assert row is None


@pytest.mark.asyncio
async def test_gsheet_add_no_valid_entries(gsheet_engine, monkeypatch):
    """Sheet is accessible but has no valid stock data."""
    import analysis_bot.services.gsheet_monitor as gsheet_mod

    async def _empty_fetch(spreadsheet_id, gid):
        return "just,some,random,data\n"

    monkeypatch.setattr(gsheet_mod, "fetch_sheet_csv", _empty_fetch)

    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=["add", TEST_GSHEET_URL]))
    assert "找不到有效" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_del_success(gsheet_engine, mock_fetch):
    # Add first
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update1, FakeContext(args=["add", TEST_GSHEET_URL]))

    # Delete
    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update2, FakeContext(args=["del", TEST_GSHEET_URL]))
    assert "✅" in msg.reply_text_calls[0].text
    assert "取消註冊" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_del_not_found(gsheet_engine, mock_fetch):
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    url = "https://docs.google.com/spreadsheets/d/notexist/edit?gid=0#gid=0"
    await handlers.gsheet_command(update, FakeContext(args=["del", url]))
    assert "❌" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_list_empty(gsheet_engine, mock_fetch):
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=["list"]))
    assert "沒有註冊" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_gsheet_list_with_entries(gsheet_engine, mock_fetch):
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update1, FakeContext(args=["add", TEST_GSHEET_URL, "短線"]))

    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update2, FakeContext(args=["list"]))
    # list is the last reply (after add's ✅ and sync result)
    list_text = msg.reply_text_calls[0].text
    assert "短線" in list_text


@pytest.mark.asyncio
async def test_gsheet_sync_no_subs(gsheet_engine, mock_fetch):
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Test")
    await handlers.gsheet_command(update, FakeContext(args=["sync"]))
    assert "⏳" in msg.reply_text_calls[0].text
    assert "沒有註冊" in msg.reply_text_calls[1].text
