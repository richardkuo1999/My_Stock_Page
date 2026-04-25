"""Tests for /info command (run_info_analysis with UAnalyze integration)."""

from unittest.mock import AsyncMock, patch

import pytest

from analysis_bot.bot.handlers import run_info_analysis
from analysis_bot.tests.bot_fakes import FakeMessage, FakeUpdate


def _update():
    msg = FakeMessage(text="/info 2330")
    return FakeUpdate(message=msg)


@pytest.mark.asyncio
async def test_info_combines_wiki_and_uanalyze():
    """run_info_analysis sends combined MoneyDJ + UAnalyze content to AI."""
    update = _update()
    captured_contents = {}

    async def fake_ai_call(_, contents=None, prompt=None, **kw):
        captured_contents["contents"] = contents
        return "AI 報告結果"

    with (
        patch(
            "analysis_bot.bot.handlers.LegacyMoneyDJ.get_wiki_result",
            return_value=("台積電", "MoneyDJ 百科內容"),
        ),
        patch(
            "analysis_bot.bot.handlers.uanalyze_analyze",
            return_value="UAnalyze 分析結果",
        ),
        patch("analysis_bot.bot.handlers.AIService") as MockAI,
    ):
        MockAI.return_value.call = AsyncMock(side_effect=fake_ai_call)
        await run_info_analysis(update, "2330")

    # Should have sent the initial ack + document (no error)
    texts = [c.text for c in update.message.reply_text_calls]
    assert any("2330" in t for t in texts)
    assert not any("❌" in t for t in texts)

    # AI received combined content
    assert "MoneyDJ 百科" in captured_contents["contents"]
    assert "UAnalyze AI 分析" in captured_contents["contents"]


@pytest.mark.asyncio
async def test_info_uanalyze_failure_still_works():
    """run_info_analysis works even when UAnalyze fails."""
    update = _update()

    with (
        patch(
            "analysis_bot.bot.handlers.LegacyMoneyDJ.get_wiki_result",
            return_value=("台積電", "MoneyDJ 百科內容"),
        ),
        patch(
            "analysis_bot.bot.handlers.uanalyze_analyze",
            side_effect=Exception("UAnalyze down"),
        ),
        patch("analysis_bot.bot.handlers.AIService") as MockAI,
    ):
        MockAI.return_value.call = AsyncMock(return_value="AI 報告")
        await run_info_analysis(update, "2330")

    texts = [c.text for c in update.message.reply_text_calls]
    assert not any("❌" in t for t in texts)


@pytest.mark.asyncio
async def test_info_no_stock_name_returns_error():
    """run_info_analysis shows error when stock not found."""
    update = _update()

    with (
        patch(
            "analysis_bot.bot.handlers.LegacyMoneyDJ.get_wiki_result",
            return_value=(None, None),
        ),
        patch(
            "analysis_bot.bot.handlers.uanalyze_analyze",
            return_value="",
        ),
    ):
        await run_info_analysis(update, "9999")

    texts = [c.text for c in update.message.reply_text_calls]
    assert any("❌" in t for t in texts)
