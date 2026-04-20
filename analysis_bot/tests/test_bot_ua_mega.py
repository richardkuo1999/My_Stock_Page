from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeContext, FakeMessage, FakeUpdate


# --- /ua ---

@pytest.mark.asyncio
async def test_ua_no_args_shows_usage() -> None:
    msg = FakeMessage()
    await handlers.ua_command(FakeUpdate(message=msg), FakeContext(args=[]))
    assert "用法" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_ua_calls_analyze(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: list[str] = []

    async def fake_analyze(stock, prompts=None):
        called_with.append(stock)
        return f"# Report for {stock}"

    monkeypatch.setattr("analysis_bot.services.uanalyze_ai.analyze_stock", fake_analyze)

    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext(args=["2330"])

    await handlers.ua_command(update, context)

    assert "2330" in called_with
    # Should have sent a document (reply_document) — but FakeMessage only tracks reply_text
    # At minimum, the "分析中" message should appear
    assert any("分析中" in c.text for c in msg.reply_text_calls)


# --- /uask ---

@pytest.mark.asyncio
async def test_uask_no_args_shows_usage() -> None:
    msg = FakeMessage()
    await handlers.uask_command(FakeUpdate(message=msg), FakeContext(args=[]))
    assert "用法" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_uask_needs_two_args() -> None:
    msg = FakeMessage()
    await handlers.uask_command(FakeUpdate(message=msg), FakeContext(args=["2330"]))
    assert "用法" in msg.reply_text_calls[-1].text


# --- /mega ---

@pytest.mark.asyncio
async def test_mega_no_args_shows_usage() -> None:
    msg = FakeMessage()
    await handlers.mega_command(FakeUpdate(message=msg), FakeContext(args=[]))
    assert "用法" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_mega_needs_two_args() -> None:
    msg = FakeMessage()
    await handlers.mega_command(FakeUpdate(message=msg), FakeContext(args=["y"]))
    assert "用法" in msg.reply_text_calls[-1].text


@pytest.mark.asyncio
async def test_mega_calls_download(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_download(should_fetch, keywords):
        return f"✅ 完成！下載 1 個"

    monkeypatch.setattr(
        "analysis_bot.services.mega_download.mega_search_and_download_async", fake_download
    )

    msg = FakeMessage()
    await handlers.mega_command(FakeUpdate(message=msg), FakeContext(args=["y", "企劃"]))

    texts = [c.text for c in msg.reply_text_calls]
    assert any("MEGA" in t for t in texts)
    assert any("完成" in t for t in texts)
