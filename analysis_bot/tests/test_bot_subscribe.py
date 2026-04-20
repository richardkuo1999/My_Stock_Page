from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate
from sqlmodel import SQLModel, create_engine


@pytest.fixture()
def sub_engine(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "sub_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    import analysis_bot.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(handlers, "engine", engine)
    return engine


# --- subscribe / unsubscribe ---

@pytest.mark.asyncio
async def test_subscribe_new(sub_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=100)
    await handlers.subscribe_command(update, FakeContext())
    assert "已訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_subscribe_duplicate(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.subscribe_command(FakeUpdate(message=msg1, chat_id=100), FakeContext())

    msg2 = FakeMessage()
    await handlers.subscribe_command(FakeUpdate(message=msg2, chat_id=100), FakeContext())
    assert "已經是訂閱者" in msg2.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsubscribe_then_resubscribe(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.subscribe_command(FakeUpdate(message=msg1, chat_id=100), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsubscribe_command(FakeUpdate(message=msg2, chat_id=100), FakeContext())
    assert "已取消" in msg2.reply_text_calls[-1].text

    msg3 = FakeMessage()
    await handlers.subscribe_command(FakeUpdate(message=msg3, chat_id=100), FakeContext())
    assert "已恢復訂閱" in msg3.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsubscribe_not_found(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsubscribe_command(FakeUpdate(message=msg, chat_id=999), FakeContext())
    assert "尚未訂閱" in msg.reply_text_calls[-1].text


# --- sub_ispike / unsub_ispike ---

@pytest.mark.asyncio
async def test_sub_ispike(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.sub_ispike_command(FakeUpdate(message=msg, chat_id=200), FakeContext())
    assert "已訂閱盤中爆量" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_ispike_not_subscribed(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsub_ispike_command(FakeUpdate(message=msg, chat_id=200), FakeContext())
    assert "尚未訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_sub_then_unsub_ispike(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_ispike_command(FakeUpdate(message=msg1, chat_id=300), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsub_ispike_command(FakeUpdate(message=msg2, chat_id=300), FakeContext())
    assert "已取消盤中爆量" in msg2.reply_text_calls[-1].text
