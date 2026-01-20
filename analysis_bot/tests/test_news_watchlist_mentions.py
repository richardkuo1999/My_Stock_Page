from __future__ import annotations

import pytest
from sqlmodel import SQLModel, Session, create_engine
from telegram.constants import ParseMode

import analysis_bot.bot.jobs as jobs
from analysis_bot.models.subscriber import Subscriber
from analysis_bot.models.watchlist import WatchlistEntry


class FakeBot:
    def __init__(self) -> None:
        self.send_message_calls = []

    async def send_message(self, *, chat_id: int, text: str, parse_mode=None, disable_web_page_preview=None, **kwargs):
        self.send_message_calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
        )


class FakeJobContext:
    def __init__(self, *, bot, bot_data):
        self.bot = bot
        self.bot_data = bot_data


@pytest.fixture()
def isolated_engine(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "news_watchlist.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    
    # Import all models to ensure they are registered
    from analysis_bot.models.watchlist import WatchlistEntry
    from analysis_bot.models.subscriber import Subscriber
    from analysis_bot.models.stock import StockData
    
    SQLModel.metadata.create_all(engine)

    # jobs.py imports engine at module import time, patch the module-level reference.
    monkeypatch.setattr(jobs, "engine", engine)
    return engine


@pytest.mark.asyncio
async def test_check_news_job_mentions_only_matching_user_by_ticker(isolated_engine):
    bot = FakeBot()

    # Seed DB: one subscriber group chat, two users with different watchlists
    with Session(isolated_engine) as session:
        session.add(Subscriber(chat_id=1000, is_active=True))
        session.add(WatchlistEntry(chat_id=1000, user_id=111, ticker="TSLA", alias="特斯拉"))
        session.add(WatchlistEntry(chat_id=1000, user_id=222, ticker="2330", alias="台積電"))
        session.commit()

    # Fake news: contains TSLA only
    from analysis_bot.tests.bot_fakes import FakeNewsParser

    parser = FakeNewsParser(
        results_by_key={
            "https://api.cnyes.com/media/api/v1/newslist/category/headline": [
                {"title": "TSLA earnings beat expectations", "url": "https://example.com/tsla"}
            ]
        }
    )
    ctx = FakeJobContext(bot=bot, bot_data={"news_parser": parser})

    await jobs.check_news_job(context=ctx)

    # Expect at least one send_message call to the subscriber chat
    calls = [c for c in bot.send_message_calls if c["chat_id"] == 1000]
    assert calls, "Expected bot to send at least one message"

    # We should see an HTML message with related keywords, without exposing user_id / tg://user links
    html_calls = [c for c in calls if c["parse_mode"] == ParseMode.HTML]
    assert html_calls, "Expected at least one HTML mention message"
    msg = html_calls[0]["text"]
    assert "tg://user?id=" not in msg
    assert "User 111" not in msg
    assert "User 222" not in msg
    assert "相關：" in msg
    assert "TSLA" in msg
    # Ensure we don't leak other user's watchlist keyword(s)
    assert "台積電" not in msg
    assert "2330" not in msg


@pytest.mark.asyncio
async def test_check_news_job_mentions_by_alias(isolated_engine):
    bot = FakeBot()

    with Session(isolated_engine) as session:
        session.add(Subscriber(chat_id=1000, is_active=True))
        session.add(WatchlistEntry(chat_id=1000, user_id=222, ticker="2330", alias="台積電"))
        session.commit()

    from analysis_bot.tests.bot_fakes import FakeNewsParser

    parser = FakeNewsParser(
        results_by_key={
            "https://api.cnyes.com/media/api/v1/newslist/category/headline": [
                {"title": "台積電 2330 發布新製程消息", "url": "https://example.com/tsmc"}
            ]
        }
    )
    ctx = FakeJobContext(bot=bot, bot_data={"news_parser": parser})

    await jobs.check_news_job(context=ctx)

    calls = [c for c in bot.send_message_calls if c["chat_id"] == 1000]
    html_calls = [c for c in calls if c["parse_mode"] == ParseMode.HTML]
    assert html_calls, "Expected at least one HTML mention message"
    msg = html_calls[0]["text"]
    assert "tg://user?id=" not in msg
    assert "User 222" not in msg
    assert "相關：" in msg
    assert "台積電" in msg

