"""Tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import echo, mention


@pytest.fixture
def update_with_text():
    """Create a mock Update with text message."""

    def _make(text: str):
        update = MagicMock()
        update.message = AsyncMock()
        update.message.text = text
        update.message.reply_text = AsyncMock()
        return update

    return _make


@pytest.fixture
def context():
    """Create a mock context."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.username = "test_bot"
    return ctx


@pytest.mark.asyncio
async def test_echo_replies_same_text(update_with_text, context):
    """Echo handler should reply with the exact same text."""
    update = update_with_text("Hello, world!")
    await echo(update, context)
    update.message.reply_text.assert_called_once_with("Hello, world!")


@pytest.mark.asyncio
async def test_echo_with_chinese_text(update_with_text, context):
    """Echo handler should work with Chinese characters."""
    update = update_with_text("台積電今天漲了")
    await echo(update, context)
    update.message.reply_text.assert_called_once_with("台積電今天漲了")


@pytest.mark.asyncio
async def test_echo_no_message(context):
    """Echo handler should not crash when message is None."""
    update = MagicMock()
    update.message = None
    await echo(update, context)  # Should not raise


@pytest.mark.asyncio
async def test_mention_detects_bot_username(context):
    """Mention handler should log when bot is mentioned."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = "@test_bot 分析台積電"
    update.effective_user = MagicMock()
    update.effective_user.id = 12345

    entity = MagicMock()
    entity.type = "mention"
    entity.offset = 0
    entity.length = 9  # len("@test_bot")
    update.message.entities = [entity]

    with patch("bot.handlers.logger") as mock_logger:
        await mention(update, context)
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert "分析台積電" in call_args[2]


@pytest.mark.asyncio
async def test_mention_ignores_other_users(context):
    """Mention handler should ignore mentions of other users."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = "@other_user hello"
    update.effective_user = MagicMock()
    update.effective_user.id = 12345

    entity = MagicMock()
    entity.type = "mention"
    entity.offset = 0
    entity.length = 11  # len("@other_user")
    update.message.entities = [entity]

    with patch("bot.handlers.logger") as mock_logger:
        await mention(update, context)
        mock_logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_mention_no_entities(context):
    """Mention handler should handle no entities gracefully."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.entities = None
    await mention(update, context)  # Should not raise
