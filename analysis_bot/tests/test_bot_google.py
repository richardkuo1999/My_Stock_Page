from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeNewsParser, FakeUpdate
from telegram.constants import ParseMode


@pytest.mark.asyncio
async def test_google_no_args_shows_usage() -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext(args=[])

    await handlers.google_command(update, context)

    assert "用法" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_google_with_keyword_returns_results() -> None:
    item = {"title": "台積電 Q1 營收", "url": "https://example.com/1"}
    # google_command builds a URL with the keyword; FakeNewsParser matches by URL key
    parser = FakeNewsParser()

    # Monkeypatch fetch_news_list to return results for any URL
    async def fake_fetch(url, news_number=15):
        return [item]

    parser.fetch_news_list = fake_fetch

    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext(args=["台積電"], bot_data={"news_parser": parser})

    await handlers.google_command(update, context)

    call = msg.reply_text_calls[-1]
    assert "台積電" in call.text
    assert "example.com" in call.text
    assert call.kwargs.get("parse_mode") == ParseMode.MARKDOWN


@pytest.mark.asyncio
async def test_google_no_results() -> None:
    parser = FakeNewsParser()

    async def fake_fetch(url, news_number=15):
        return []

    parser.fetch_news_list = fake_fetch

    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext(args=["不存在"], bot_data={"news_parser": parser})

    await handlers.google_command(update, context)

    assert "找不到" in msg.reply_text_calls[-1].text
