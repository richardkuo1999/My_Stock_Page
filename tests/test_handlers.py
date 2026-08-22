"""Tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import mention


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
