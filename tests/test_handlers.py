"""Tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import (
    help_command,
    kchart_command,
    mention,
    price_command,
    start_command,
    uanalyze_command,
)


@pytest.fixture
def context():
    """Create a mock context."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.username = "test_bot"
    ctx.bot_data = {}
    return ctx


@pytest.fixture
def mock_bridge():
    """Create a mock AgentBridge."""
    bridge = AsyncMock()
    bridge.send = AsyncMock(return_value="Agent 回覆內容")
    return bridge


def _make_mention_update(text: str, bot_name: str = "test_bot"):
    """Helper to create an update with a mention entity."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345

    mention_str = f"@{bot_name}"
    offset = text.find(mention_str)
    entity = MagicMock()
    entity.type = "mention"
    entity.offset = offset
    entity.length = len(mention_str)
    update.message.entities = [entity]
    return update


# --- Mention + Agent routing tests ---


@pytest.mark.asyncio
async def test_mention_routes_to_bridge(context, mock_bridge):
    """Mention handler routes text to bridge and replies with response."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot 分析台積電")

    await mention(update, context)

    # The handler wraps the question with the system prompt before sending.
    mock_bridge.send.assert_called_once()
    sent_prompt = mock_bridge.send.call_args[0][0]
    assert "分析台積電" in sent_prompt
    assert "台股投資輔助助理" in sent_prompt  # system prompt is prepended
    update.message.reply_text.assert_called_once_with("Agent 回覆內容")


@pytest.mark.asyncio
async def test_mention_timeout_error(context, mock_bridge):
    """Mention handler replies with timeout message on TimeoutError."""
    mock_bridge.send = AsyncMock(side_effect=TimeoutError("timed out"))
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot 很慢的問題")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 暫時無法回應，請稍後再試")


@pytest.mark.asyncio
async def test_mention_runtime_error(context, mock_bridge):
    """Mention handler replies with error message on RuntimeError."""
    mock_bridge.send = AsyncMock(side_effect=RuntimeError("Agent error (code 1): fail"))
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot 壞掉的指令")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 發生錯誤，請稍後再試")


@pytest.mark.asyncio
async def test_mention_empty_text(context, mock_bridge):
    """Mention handler prompts user when no text follows the mention."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("請在 @mention 後加上您的問題")
    mock_bridge.send.assert_not_called()


@pytest.mark.asyncio
async def test_mention_no_bridge(context):
    """Mention handler replies with setup message when bridge not configured."""
    # bot_data has no "agent_bridge" key
    update = _make_mention_update("@test_bot 問題")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 未設定")


@pytest.mark.asyncio
async def test_mention_ignores_other_users(context):
    """Mention handler should ignore mentions of other users."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = "@other_user hello"
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345

    entity = MagicMock()
    entity.type = "mention"
    entity.offset = 0
    entity.length = 11  # len("@other_user")
    update.message.entities = [entity]

    await mention(update, context)
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_mention_no_entities(context):
    """Mention handler should handle no entities gracefully."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.entities = None
    await mention(update, context)  # Should not raise


# --- /start, /help and quick command tests ---


def _make_command_update(text: str):
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_start_command_greets(context):
    update = _make_command_update("/start")
    await start_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "台股" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_help_command_lists_commands(context):
    update = _make_command_update("/help")
    await help_command(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "/p" in text and "/k" in text and "/ua" in text


@pytest.mark.asyncio
async def test_price_command_no_arg(context):
    update = _make_command_update("/p")
    await price_command(update, context)
    assert "用法" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_price_command_success(context):
    update = _make_command_update("/p 2330")
    fake = {"symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0, "change_pct": 1.47, "volume": 0, "source": "fugle"}
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)):
        await price_command(update, context)
    # last reply carries the price info
    text = update.message.reply_text.call_args[0][0]
    assert "台積電" in text and "2410" in text


@pytest.mark.asyncio
async def test_price_command_error(context):
    update = _make_command_update("/p 9999")
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value={"error": "找不到股票代號 9999"})):
        await price_command(update, context)
    assert "找不到" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_kchart_command_sends_photo(context, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n")
    update = _make_command_update("/k 2330 60")
    with patch("tools.draw_kchart.draw", new=AsyncMock(return_value={"image_path": str(img)})):
        await kchart_command(update, context)
    update.message.reply_photo.assert_awaited_once()


@pytest.mark.asyncio
async def test_kchart_command_error(context):
    update = _make_command_update("/k 9999")
    with patch("tools.draw_kchart.draw", new=AsyncMock(return_value={"error": "找不到股票代號 9999 的歷史資料"})):
        await kchart_command(update, context)
    # reply_text called with error (after the "正在繪製" message)
    assert any("找不到" in c.args[0] for c in update.message.reply_text.call_args_list)


@pytest.mark.asyncio
async def test_uanalyze_command_success(context):
    update = _make_command_update("/ua 2330")
    with patch("tools.uanalyze.analyze", new=AsyncMock(return_value={"analysis": "台積電近況良好"})):
        await uanalyze_command(update, context)
    assert any("台積電近況良好" in c.args[0] for c in update.message.reply_text.call_args_list)
