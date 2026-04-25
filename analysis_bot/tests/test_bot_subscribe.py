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


# --- sub_news / unsub_news ---

@pytest.mark.asyncio
async def test_sub_news_new(sub_engine) -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=100)
    await handlers.sub_news_command(update, FakeContext())
    assert "已訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_sub_news_duplicate(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_news_command(FakeUpdate(message=msg1, chat_id=100), FakeContext())

    msg2 = FakeMessage()
    await handlers.sub_news_command(FakeUpdate(message=msg2, chat_id=100), FakeContext())
    assert "已經是訂閱者" in msg2.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_news_then_resub(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_news_command(FakeUpdate(message=msg1, chat_id=100), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsub_news_command(FakeUpdate(message=msg2, chat_id=100), FakeContext())
    assert "已取消" in msg2.reply_text_calls[-1].text

    msg3 = FakeMessage()
    await handlers.sub_news_command(FakeUpdate(message=msg3, chat_id=100), FakeContext())
    assert "已恢復訂閱" in msg3.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_news_not_found(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsub_news_command(FakeUpdate(message=msg, chat_id=999), FakeContext())
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


# --- sub_senti / unsub_senti ---

@pytest.mark.asyncio
async def test_sub_senti(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.sub_senti_command(FakeUpdate(message=msg, chat_id=400), FakeContext())
    assert "已訂閱情緒警報" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_senti_not_subscribed(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsub_senti_command(FakeUpdate(message=msg, chat_id=400), FakeContext())
    assert "尚未訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_sub_then_unsub_senti(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_senti_command(FakeUpdate(message=msg1, chat_id=500), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsub_senti_command(FakeUpdate(message=msg2, chat_id=500), FakeContext())
    assert "已取消情緒警報" in msg2.reply_text_calls[-1].text


# --- topic_id isolation ---

@pytest.mark.asyncio
async def test_sub_news_different_topics(sub_engine) -> None:
    """Same chat_id but different topic_id should create separate subscriptions."""
    msg1 = FakeMessage()
    await handlers.sub_news_command(
        FakeUpdate(message=msg1, chat_id=600), FakeContext()
    )
    assert "已訂閱" in msg1.reply_text_calls[-1].text

    msg2 = FakeMessage(message_thread_id=42)
    await handlers.sub_news_command(
        FakeUpdate(message=msg2, chat_id=600), FakeContext()
    )
    assert "已訂閱" in msg2.reply_text_calls[-1].text  # new, not duplicate


# --- sub_daily / unsub_daily ---

@pytest.mark.asyncio
async def test_sub_daily(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.sub_daily_command(FakeUpdate(message=msg, chat_id=700), FakeContext())
    assert "已訂閱每日分析" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_daily_not_subscribed(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsub_daily_command(FakeUpdate(message=msg, chat_id=700), FakeContext())
    assert "尚未訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_sub_then_unsub_daily(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_daily_command(FakeUpdate(message=msg1, chat_id=800), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsub_daily_command(FakeUpdate(message=msg2, chat_id=800), FakeContext())
    assert "已取消每日分析" in msg2.reply_text_calls[-1].text


# --- sub_spike / unsub_spike ---

@pytest.mark.asyncio
async def test_sub_spike(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.sub_spike_command(FakeUpdate(message=msg, chat_id=900), FakeContext())
    assert "已訂閱收盤爆量" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_spike_not_subscribed(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsub_spike_command(FakeUpdate(message=msg, chat_id=900), FakeContext())
    assert "尚未訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_sub_then_unsub_spike(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_spike_command(FakeUpdate(message=msg1, chat_id=1000), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsub_spike_command(FakeUpdate(message=msg2, chat_id=1000), FakeContext())
    assert "已取消收盤爆量" in msg2.reply_text_calls[-1].text


# --- sub_vix / unsub_vix ---

@pytest.mark.asyncio
async def test_sub_vix(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.sub_vix_command(FakeUpdate(message=msg, chat_id=1100), FakeContext())
    assert "已訂閱 VIX" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_unsub_vix_not_subscribed(sub_engine) -> None:
    msg = FakeMessage()
    await handlers.unsub_vix_command(FakeUpdate(message=msg, chat_id=1100), FakeContext())
    assert "尚未訂閱" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_sub_then_unsub_vix(sub_engine) -> None:
    msg1 = FakeMessage()
    await handlers.sub_vix_command(FakeUpdate(message=msg1, chat_id=1200), FakeContext())

    msg2 = FakeMessage()
    await handlers.unsub_vix_command(FakeUpdate(message=msg2, chat_id=1200), FakeContext())
    assert "已取消 VIX" in msg2.reply_text_calls[-1].text