from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate


@pytest.mark.asyncio
async def test_name_command_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_or_analyze_stock(ticker: str, force_update: bool = False):
        return {"name": "台積電"}, True

    monkeypatch.setattr(handlers.StockService, "get_or_analyze_stock", fake_get_or_analyze_stock)

    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10)
    context = FakeContext(args=["2330"])

    await handlers.name_command(update, context)

    assert msg.reply_text_calls
    assert "公司名稱：台積電" in msg.reply_text_calls[-1].text
    assert "Ticker：2330" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_name_command_usage_no_args() -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg, chat_id=1, user_id=10)
    context = FakeContext(args=[])

    await handlers.name_command(update, context)

    assert msg.reply_text_calls[-1].text.startswith("用法：/name")
