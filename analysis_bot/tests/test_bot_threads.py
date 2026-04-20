from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate
from sqlmodel import SQLModel, create_engine


@pytest.fixture()
def threads_engine(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "threads_test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    import analysis_bot.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(handlers, "engine", engine)
    return engine


@pytest.mark.asyncio
async def test_threads_usage_no_args(threads_engine) -> None:
    msg = FakeMessage()
    await handlers.threads_command(FakeUpdate(message=msg, chat_id=1), FakeContext(args=[]))
    assert "Threads" in msg.reply_text_calls[-1].text
    assert "/threads add" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_threads_add_list_remove(threads_engine) -> None:
    # add
    msg1 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg1, chat_id=1), FakeContext(args=["add", "testuser"])
    )
    assert "已訂閱" in msg1.reply_text_calls[-1].text
    assert "testuser" in msg1.reply_text_calls[-1].text

    # add duplicate
    msg2 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg2, chat_id=1), FakeContext(args=["add", "testuser"])
    )
    assert "已訂閱" in msg2.reply_text_calls[-1].text  # ℹ️ 已訂閱

    # list
    msg3 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg3, chat_id=1), FakeContext(args=["list"])
    )
    assert "testuser" in msg3.reply_text_calls[-1].text

    # remove
    msg4 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg4, chat_id=1), FakeContext(args=["remove", "testuser"])
    )
    assert "已取消" in msg4.reply_text_calls[-1].text

    # list empty
    msg5 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg5, chat_id=1), FakeContext(args=["list"])
    )
    assert "尚無" in msg5.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_threads_remove_not_found(threads_engine) -> None:
    msg = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg, chat_id=1), FakeContext(args=["remove", "nobody"])
    )
    assert "未訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_threads_invalid_username(threads_engine) -> None:
    msg = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg, chat_id=1), FakeContext(args=["add", "bad user!"])
    )
    assert "格式不正確" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_threads_per_chat(threads_engine) -> None:
    # add in chat 1
    msg1 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg1, chat_id=1), FakeContext(args=["add", "user1"])
    )

    # list in chat 2 is empty
    msg2 = FakeMessage()
    await handlers.threads_command(
        FakeUpdate(message=msg2, chat_id=2), FakeContext(args=["list"])
    )
    assert "尚無" in msg2.reply_text_calls[-1].text
