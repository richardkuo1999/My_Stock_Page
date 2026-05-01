from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate
from sqlmodel import SQLModel, create_engine


@pytest.fixture()
def watchlist_engine(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "watchlist_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    import analysis_bot.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(handlers, "engine", engine)
    return engine


# --- /wadd ---

@pytest.mark.asyncio
async def test_wadd_no_args(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update, FakeContext(args=[]))
    assert msg.reply_text_calls[0].text.startswith("用法：/wadd")


@pytest.mark.asyncio
async def test_wadd_basic(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update, FakeContext(args=["2330"]))
    text = msg.reply_text_calls[-1].text
    assert "✅ 已加入：2330" in text
    assert "📌 自選股清單" in text
    assert "👤 Richard:" in text


@pytest.mark.asyncio
async def test_wadd_with_note(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update, FakeContext(args=["2330", "長期持有"]))
    text = msg.reply_text_calls[-1].text
    assert "✅ 已加入：2330" in text
    # Compact mode doesn't show notes; hint to use /wlist full is shown
    assert "/wlist full" in text


@pytest.mark.asyncio
async def test_wadd_duplicate(watchlist_engine) -> None:
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update1, FakeContext(args=["2330"]))

    msg2 = FakeMessage()
    update2 = FakeUpdate(message=msg2, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update2, FakeContext(args=["2330"]))
    assert msg2.reply_text_calls[-1].text == "ℹ️ 已存在：2330"


@pytest.mark.asyncio
async def test_wadd_bad_ticker(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update, FakeContext(args=["bad ticker!"]))
    assert msg.reply_text_calls[-1].text == "❌ Ticker 格式不正確"


# --- /wdel ---

@pytest.mark.asyncio
async def test_wdel_no_args(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wdel_command(update, FakeContext(args=[]))
    assert msg.reply_text_calls[0].text.startswith("用法：/wdel")


@pytest.mark.asyncio
async def test_wdel_not_found(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wdel_command(update, FakeContext(args=["2330"]))
    assert msg.reply_text_calls[-1].text == "ℹ️ 不在清單：2330"


@pytest.mark.asyncio
async def test_wdel_basic(watchlist_engine) -> None:
    # Add first
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update1, FakeContext(args=["TSLA"]))

    # Delete
    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wdel_command(update2, FakeContext(args=["TSLA"]))
    text = msg.reply_text_calls[-1].text
    assert "✅ 已移除：TSLA" in text
    assert "目前沒有自選股" in text


@pytest.mark.asyncio
async def test_wdel_with_profit(watchlist_engine, monkeypatch) -> None:
    """When added_price exists and current price is higher, show profit."""
    from sqlmodel import Session
    from analysis_bot.models.stock import StockData

    # Seed StockData with a price
    with Session(watchlist_engine) as session:
        session.add(StockData(ticker="2330", name="台積電", price=1000.0))
        session.commit()

    # Add (will pick up price=1000 from StockData)
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update1, FakeContext(args=["2330"]))

    # Update price to simulate gain
    with Session(watchlist_engine) as session:
        stock = session.exec(
            __import__("sqlmodel").select(StockData).where(StockData.ticker == "2330")
        ).first()
        stock.price = 1100.0
        session.add(stock)
        session.commit()

    # Delete
    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wdel_command(update2, FakeContext(args=["2330"]))
    text = msg.reply_text_calls[-1].text
    assert "🎉 恭喜" in text
    assert "+10.00%" in text


@pytest.mark.asyncio
async def test_wdel_with_loss(watchlist_engine) -> None:
    """When current price is lower, show loss message."""
    from sqlmodel import Session
    from analysis_bot.models.stock import StockData

    with Session(watchlist_engine) as session:
        session.add(StockData(ticker="2330", name="台積電", price=1000.0))
        session.commit()

    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update1, FakeContext(args=["2330"]))

    with Session(watchlist_engine) as session:
        stock = session.exec(
            __import__("sqlmodel").select(StockData).where(StockData.ticker == "2330")
        ).first()
        stock.price = 900.0
        session.add(stock)
        session.commit()

    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wdel_command(update2, FakeContext(args=["2330"]))
    text = msg.reply_text_calls[-1].text
    assert "💪 下次加油" in text
    assert "-10.00%" in text


# --- /wlist ---

@pytest.mark.asyncio
async def test_wlist_empty(watchlist_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wlist_command(update, FakeContext())
    assert msg.reply_text_calls[-1].text == "📌 目前沒有自選股"


@pytest.mark.asyncio
async def test_wlist_grouped_by_user(watchlist_engine) -> None:
    # User 10 adds
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update1, FakeContext(args=["TSLA"]))

    # User 20 adds
    update2 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=20, user_full_name="Alice")
    await handlers.wadd_command(update2, FakeContext(args=["AAPL"]))

    # List shows both
    msg = FakeMessage()
    update3 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wlist_command(update3, FakeContext())
    text = msg.reply_text_calls[-1].text
    assert "👤 Richard:" in text
    assert "TSLA" in text
    assert "👤 Alice:" in text
    assert "AAPL" in text


@pytest.mark.asyncio
async def test_wlist_per_chat(watchlist_engine) -> None:
    # Add to chat 1
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="Richard")
    await handlers.wadd_command(update1, FakeContext(args=["TSLA"]))

    # List in chat 2 is empty
    msg = FakeMessage()
    update2 = FakeUpdate(message=msg, chat_id=2, user_id=10, user_full_name="Richard")
    await handlers.wlist_command(update2, FakeContext())
    assert msg.reply_text_calls[-1].text == "📌 目前沒有自選股"


# --- user_name update ---

@pytest.mark.asyncio
async def test_user_name_updated_on_wadd(watchlist_engine) -> None:
    """When user changes name, wadd updates all their entries."""
    # Add with old name
    update1 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="OldName")
    await handlers.wadd_command(update1, FakeContext(args=["TSLA"]))

    # Add another with new name
    update2 = FakeUpdate(message=FakeMessage(), chat_id=1, user_id=10, user_full_name="NewName")
    await handlers.wadd_command(update2, FakeContext(args=["AAPL"]))

    # List should show NewName for both
    msg = FakeMessage()
    update3 = FakeUpdate(message=msg, chat_id=1, user_id=10, user_full_name="NewName")
    await handlers.wlist_command(update3, FakeContext())
    text = msg.reply_text_calls[-1].text
    assert "👤 NewName:" in text
    assert "OldName" not in text
