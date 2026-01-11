from __future__ import annotations

import pytest
from sqlmodel import SQLModel, create_engine

from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate


@pytest.fixture()
def watchlist_engine(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "watchlist_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    
    # Import all models to ensure they are registered
    from analysis_bot.models.watchlist import WatchlistEntry
    from analysis_bot.models.subscriber import Subscriber
    from analysis_bot.models.stock import StockData
    
    SQLModel.metadata.create_all(engine)

    import analysis_bot.database as database

    monkeypatch.setattr(database, "engine", engine)
    return engine


@pytest.mark.asyncio
async def test_watch_usage_no_args(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10)
    context = FakeContext(args=[])

    await handlers.watch_command(update, context)

    assert len(msg.reply_text_calls) == 1
    assert msg.reply_text_calls[0].text.startswith("用法：/watch")


@pytest.mark.asyncio
async def test_watch_add_list_remove_flow(watchlist_engine) -> None:
    # add
    msg1 = FakeMessage()
    update1 = FakeUpdate(message=msg1, chat_id=1, user_id=10)
    context1 = FakeContext(args=["add", "2330", "台積電"])
    await handlers.watch_command(update1, context1)
    assert msg1.reply_text_calls[-1].text == "✅ 已加入：2330（台積電）"

    # add duplicate
    msg2 = FakeMessage()
    update2 = FakeUpdate(message=msg2, chat_id=1, user_id=10)
    context2 = FakeContext(args=["add", "2330"])
    await handlers.watch_command(update2, context2)
    assert msg2.reply_text_calls[-1].text == "ℹ️ 已存在：2330"

    # list contains
    msg3 = FakeMessage()
    update3 = FakeUpdate(message=msg3, chat_id=1, user_id=10)
    context3 = FakeContext(args=["list"])
    await handlers.watch_command(update3, context3)
    txt = msg3.reply_text_calls[-1].text
    assert "你的自選股" in txt
    assert "2330" in txt

    # remove
    msg4 = FakeMessage()
    update4 = FakeUpdate(message=msg4, chat_id=1, user_id=10)
    context4 = FakeContext(args=["remove", "2330"])
    await handlers.watch_command(update4, context4)
    assert msg4.reply_text_calls[-1].text == "✅ 已移除：2330"

    # list empty
    msg5 = FakeMessage()
    update5 = FakeUpdate(message=msg5, chat_id=1, user_id=10)
    context5 = FakeContext(args=["list"])
    await handlers.watch_command(update5, context5)
    assert msg5.reply_text_calls[-1].text == "目前沒有自選股"


@pytest.mark.asyncio
async def test_watch_remove_not_found(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10)
    context = FakeContext(args=["remove", "2330"])

    await handlers.watch_command(update, context)

    assert msg.reply_text_calls[-1].text == "ℹ️ 不在清單：2330"


@pytest.mark.asyncio
async def test_watch_ticker_validation(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10)
    context = FakeContext(args=["add", "bad ticker!"])

    await handlers.watch_command(update, context)

    assert msg.reply_text_calls[-1].text == "Ticker 格式不正確"


@pytest.mark.asyncio
async def test_watch_is_per_chat(watchlist_engine) -> None:
    # add to chat 1
    msg1 = FakeMessage()
    await handlers.watch_command(FakeUpdate(message=msg1, chat_id=1, user_id=10), FakeContext(args=["add", "TSLA"]))
    assert msg1.reply_text_calls[-1].text == "✅ 已加入：TSLA"

    # list in chat 2 is empty
    msg2 = FakeMessage()
    await handlers.watch_command(FakeUpdate(message=msg2, chat_id=2, user_id=10), FakeContext(args=["list"]))
    assert msg2.reply_text_calls[-1].text == "目前沒有自選股"


@pytest.mark.asyncio
async def test_watch_is_per_user_in_same_chat(watchlist_engine) -> None:
    # user 10 adds
    msg1 = FakeMessage()
    await handlers.watch_command(FakeUpdate(message=msg1, chat_id=1, user_id=10), FakeContext(args=["add", "TSLA"]))
    assert msg1.reply_text_calls[-1].text == "✅ 已加入：TSLA"

    # user 20 lists empty
    msg2 = FakeMessage()
    await handlers.watch_command(FakeUpdate(message=msg2, chat_id=1, user_id=20), FakeContext(args=["list"]))
    assert msg2.reply_text_calls[-1].text == "目前沒有自選股"


@pytest.mark.asyncio
async def test_watch_add_auto_alias_from_stock_service(watchlist_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_or_analyze_stock(ticker: str, force_update: bool = False):
        return {"name": "台積電"}, False

    monkeypatch.setattr(handlers.StockService, "get_or_analyze_stock", fake_get_or_analyze_stock)

    msg1 = FakeMessage()
    await handlers.watch_command(
        FakeUpdate(message=msg1, chat_id=1, user_id=10),
        FakeContext(args=["add", "2330"]),
    )
    assert msg1.reply_text_calls[-1].text == "✅ 已加入：2330（台積電）"

    # list shows alias
    msg2 = FakeMessage()
    await handlers.watch_command(
        FakeUpdate(message=msg2, chat_id=1, user_id=10),
        FakeContext(args=["list"]),
    )
    assert "2330（台積電）" in msg2.reply_text_calls[-1].text

