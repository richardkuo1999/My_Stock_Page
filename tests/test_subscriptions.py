"""Tests for bot/subscriptions.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.subscriptions import (
    SubscriptionManager,
    news_now_handler,
    sub_news_handler,
    sub_threads_handler,
    threads_now_handler,
    unsub_news_handler,
    unsub_threads_handler,
)


@pytest.fixture
def manager(tmp_path):
    """Create a SubscriptionManager with an isolated temp file."""
    path = tmp_path / "subscriptions.json"
    return SubscriptionManager(path=str(path))


@pytest.fixture
def update():
    """Create a mock Update with effective_chat."""
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = 12345
    u.message = AsyncMock()
    u.message.reply_text = AsyncMock()
    return u


@pytest.fixture
def context():
    """Create a mock context."""
    return MagicMock()


# --- SubscriptionManager unit tests ---


class TestSubscribe:
    """Tests for SubscriptionManager.subscribe."""

    def test_subscribe_adds_entry(self, manager):
        """First subscription should return True and add the entry."""
        result = manager.subscribe(12345, "news")
        assert result is True
        assert 12345 in manager.get_subscribers("news")

    def test_subscribe_duplicate_returns_false(self, manager):
        """Duplicate subscription should return False."""
        manager.subscribe(12345, "news")
        result = manager.subscribe(12345, "news")
        assert result is False

    def test_subscribe_duplicate_no_duplicate_record(self, manager):
        """Duplicate subscription should not create duplicate records."""
        manager.subscribe(12345, "news")
        manager.subscribe(12345, "news")
        assert manager.get_subscribers("news") == [12345]

    def test_subscribe_multiple_users(self, manager):
        """Multiple different users can subscribe."""
        manager.subscribe(111, "news")
        manager.subscribe(222, "news")
        assert set(manager.get_subscribers("news")) == {111, 222}

    def test_subscribe_different_channels(self, manager):
        """Subscribing to different channels works independently."""
        manager.subscribe(12345, "news")
        manager.subscribe(12345, "threads")
        assert 12345 in manager.get_subscribers("news")
        assert 12345 in manager.get_subscribers("threads")

    def test_subscribe_stores_timestamp(self, manager):
        """Subscription entry should have a subscribed_at timestamp."""
        manager.subscribe(12345, "news")
        entry = manager._data["news"][0]
        assert "subscribed_at" in entry
        assert "T" in entry["subscribed_at"]  # ISO format


class TestUnsubscribe:
    """Tests for SubscriptionManager.unsubscribe."""

    def test_unsubscribe_removes_entry(self, manager):
        """Unsubscribing should remove the entry and return True."""
        manager.subscribe(12345, "news")
        result = manager.unsubscribe(12345, "news")
        assert result is True
        assert 12345 not in manager.get_subscribers("news")

    def test_unsubscribe_not_subscribed_returns_false(self, manager):
        """Unsubscribing when not subscribed should return False."""
        result = manager.unsubscribe(12345, "news")
        assert result is False

    def test_unsubscribe_unknown_channel_returns_false(self, manager):
        """Unsubscribing from unknown channel should return False."""
        result = manager.unsubscribe(12345, "unknown_channel")
        assert result is False

    def test_unsubscribe_leaves_other_users(self, manager):
        """Unsubscribing one user should not affect others."""
        manager.subscribe(111, "news")
        manager.subscribe(222, "news")
        manager.unsubscribe(111, "news")
        assert manager.get_subscribers("news") == [222]


class TestGetSubscribers:
    """Tests for SubscriptionManager.get_subscribers."""

    def test_get_subscribers_empty_channel(self, manager):
        """Empty channel returns empty list."""
        assert manager.get_subscribers("news") == []

    def test_get_subscribers_unknown_channel(self, manager):
        """Unknown channel returns empty list."""
        assert manager.get_subscribers("nonexistent") == []

    def test_get_subscribers_returns_chat_ids(self, manager):
        """Should return only chat_id integers."""
        manager.subscribe(111, "threads")
        manager.subscribe(222, "threads")
        result = manager.get_subscribers("threads")
        assert result == [111, 222]


class TestPersistence:
    """Tests for file persistence."""

    def test_data_survives_restart(self, tmp_path):
        """Data written by one manager instance should be readable by another."""
        path = str(tmp_path / "subscriptions.json")
        m1 = SubscriptionManager(path=path)
        m1.subscribe(12345, "news")
        m1.subscribe(67890, "threads")

        # Create a new instance (simulates restart)
        m2 = SubscriptionManager(path=path)
        assert 12345 in m2.get_subscribers("news")
        assert 67890 in m2.get_subscribers("threads")

    def test_file_format_matches_spec(self, tmp_path):
        """Persisted JSON should match the ARCHITECTURE.md format."""
        path = tmp_path / "subscriptions.json"
        m = SubscriptionManager(path=str(path))
        m.subscribe(12345, "news")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "news" in data
        assert "threads" in data
        assert len(data["news"]) == 1
        assert data["news"][0]["chat_id"] == 12345
        assert "subscribed_at" in data["news"][0]

    def test_creates_parent_directory(self, tmp_path):
        """Should create parent directories if they don't exist."""
        path = str(tmp_path / "nested" / "dir" / "subs.json")
        m = SubscriptionManager(path=path)
        m.subscribe(12345, "news")
        # No exception means success
        assert 12345 in m.get_subscribers("news")

    def test_handles_corrupted_file(self, tmp_path):
        """Should handle corrupted JSON gracefully."""
        path = tmp_path / "subscriptions.json"
        path.write_text("not valid json{{{", encoding="utf-8")
        m = SubscriptionManager(path=str(path))
        # Should start fresh
        assert m.get_subscribers("news") == []


# --- Command handler tests ---


@pytest.mark.asyncio
async def test_sub_news_handler_new_subscription(update, context):
    """sub_news_handler should reply confirmation for new subscription."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = True
        await sub_news_handler(update, context)
        mock_manager.subscribe.assert_called_once_with(12345, "news")
        update.message.reply_text.assert_called_once_with("✅ 已訂閱新聞推播")


@pytest.mark.asyncio
async def test_sub_news_handler_already_subscribed(update, context):
    """sub_news_handler should reply info if already subscribed."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = False
        await sub_news_handler(update, context)
        update.message.reply_text.assert_called_once_with("ℹ️ 您已經訂閱新聞推播")


@pytest.mark.asyncio
async def test_unsub_news_handler_success(update, context):
    """unsub_news_handler should reply confirmation on successful unsubscribe."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.unsubscribe.return_value = True
        await unsub_news_handler(update, context)
        mock_manager.unsubscribe.assert_called_once_with(12345, "news")
        update.message.reply_text.assert_called_once_with("✅ 已取消新聞推播")


@pytest.mark.asyncio
async def test_unsub_news_handler_not_subscribed(update, context):
    """unsub_news_handler should reply info if not subscribed."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.unsubscribe.return_value = False
        await unsub_news_handler(update, context)
        update.message.reply_text.assert_called_once_with("ℹ️ 您尚未訂閱新聞推播")


@pytest.mark.asyncio
async def test_sub_threads_handler_new_subscription(update, context):
    """sub_threads_handler should reply confirmation for new subscription."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = True
        await sub_threads_handler(update, context)
        mock_manager.subscribe.assert_called_once_with(12345, "threads")
        update.message.reply_text.assert_called_once_with("✅ 已訂閱 Threads 推播")


@pytest.mark.asyncio
async def test_sub_threads_handler_already_subscribed(update, context):
    """sub_threads_handler should reply info if already subscribed."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = False
        await sub_threads_handler(update, context)
        update.message.reply_text.assert_called_once_with("ℹ️ 您已經訂閱 Threads 推播")


@pytest.mark.asyncio
async def test_unsub_threads_handler_success(update, context):
    """unsub_threads_handler should reply confirmation on successful unsubscribe."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.unsubscribe.return_value = True
        await unsub_threads_handler(update, context)
        mock_manager.unsubscribe.assert_called_once_with(12345, "threads")
        update.message.reply_text.assert_called_once_with("✅ 已取消 Threads 推播")


@pytest.mark.asyncio
async def test_unsub_threads_handler_not_subscribed(update, context):
    """unsub_threads_handler should reply info if not subscribed."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.unsubscribe.return_value = False
        await unsub_threads_handler(update, context)
        update.message.reply_text.assert_called_once_with("ℹ️ 您尚未訂閱 Threads 推播")


@pytest.mark.asyncio
async def test_handler_no_effective_chat(context):
    """Handlers should handle missing effective_chat gracefully."""
    update = MagicMock()
    update.effective_chat = None
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()

    with patch("bot.subscriptions.manager") as mock_manager:
        await sub_news_handler(update, context)
        mock_manager.subscribe.assert_not_called()
        update.message.reply_text.assert_not_called()


# --- /news command handler tests ---


@pytest.fixture
def news_context():
    """Context with an explicit bot_data (no agent bridge)."""
    ctx = MagicMock()
    ctx.bot_data = {"agent_bridge": None}
    return ctx


@pytest.mark.asyncio
async def test_news_now_handler_success(update, news_context):
    """news_now_handler should fetch and reply with a formatted list."""
    fake = {"articles": [
        {"title": "台積電創新高", "source": "CNYES", "url": "https://x/1"},
        {"title": "聯發科法說", "source": "CNYES", "url": "https://x/2"},
    ]}
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_now_handler(update, news_context)

    # First reply is the "fetching" notice, last is the results
    assert update.message.reply_text.call_count == 2
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "最新新聞" in last_msg
    assert "台積電創新高" in last_msg
    assert "https://x/1" in last_msg


@pytest.mark.asyncio
async def test_news_now_handler_empty(update, news_context):
    """news_now_handler should report when no news found."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": []}):
        await news_now_handler(update, news_context)
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "沒有抓到" in last_msg


@pytest.mark.asyncio
async def test_news_now_handler_fetch_error(update, news_context):
    """news_now_handler should report fetch errors."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        await news_now_handler(update, news_context)
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "錯誤" in last_msg


@pytest.mark.asyncio
async def test_news_now_handler_uses_agent_summary(update):
    """news_now_handler should use agent summary when bridge available."""
    fake = {"articles": [{"title": "T", "source": "S", "url": "https://x/1"}]}
    bridge = MagicMock()
    bridge.send = AsyncMock(return_value="• [S] 摘要內容\n  └ https://x/1")
    ctx = MagicMock()
    ctx.bot_data = {"agent_bridge": bridge}

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_now_handler(update, ctx)

    bridge.send.assert_awaited_once()
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "摘要內容" in last_msg


@pytest.mark.asyncio
async def test_news_now_handler_agent_fallback(update):
    """news_now_handler should fall back to plain list if agent fails."""
    fake = {"articles": [{"title": "標題X", "source": "CNYES", "url": "https://x/1"}]}
    bridge = MagicMock()
    bridge.send = AsyncMock(side_effect=TimeoutError())
    ctx = MagicMock()
    ctx.bot_data = {"agent_bridge": bridge}

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_now_handler(update, ctx)

    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "標題X" in last_msg
    assert "https://x/1" in last_msg


# --- /threads command handler tests ---


@pytest.mark.asyncio
async def test_threads_now_handler_success(update, news_context):
    """threads_now_handler should fetch and reply with posts."""
    fake = {"posts": [
        {"id": "1", "user": "alice", "text": "貼文一", "timestamp": "2026-08-22T00:00:00", "url": "https://t/1"},
        {"id": "2", "user": "bob", "text": "貼文二", "timestamp": "2026-08-21T00:00:00", "url": "https://t/2"},
    ]}
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value=fake):
        await threads_now_handler(update, news_context)

    # 1 fetching notice + 2 posts
    assert update.message.reply_text.call_count == 3
    msgs = "".join(c[0][0] for c in update.message.reply_text.call_args_list)
    assert "貼文一" in msgs
    assert "貼文二" in msgs


@pytest.mark.asyncio
async def test_threads_now_handler_empty(update, news_context):
    """threads_now_handler should report when no posts found."""
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"posts": []}):
        await threads_now_handler(update, news_context)
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "沒有抓到" in last_msg


@pytest.mark.asyncio
async def test_threads_now_handler_error_result(update, news_context):
    """threads_now_handler should surface API error (e.g. token expired)."""
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock,
               return_value={"error": "Threads token 已過期，請重新獲取 access token"}):
        await threads_now_handler(update, news_context)
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "token" in last_msg.lower()


@pytest.mark.asyncio
async def test_threads_now_handler_fetch_exception(update, news_context):
    """threads_now_handler should report unexpected fetch errors."""
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        await threads_now_handler(update, news_context)
    last_msg = update.message.reply_text.call_args_list[-1][0][0]
    assert "錯誤" in last_msg
