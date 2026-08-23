"""Tests for bot/subscriptions.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.subscriptions import (
    SubscriptionManager,
    news_now_handler,
    news_source_callback,
    sub_news_handler,
    sub_threads_handler,
    sub_uanalyze_handler,
    threads_now_handler,
    unsub_news_handler,
    unsub_threads_handler,
    unsub_uanalyze_handler,
)


@pytest.fixture
def manager(tmp_path):
    """Create a SubscriptionManager with an isolated temp file."""
    path = tmp_path / "subscriptions.json"
    return SubscriptionManager(path=str(path))


@pytest.fixture
def update():
    """Create a mock Update for a private chat (no forum topic)."""
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = 12345
    u.message = AsyncMock()
    u.message.reply_text = AsyncMock()
    u.message.message_thread_id = None  # private chat / General thread
    return u


@pytest.fixture
def group_topic_update():
    """Create a mock Update sent inside a group forum topic (message_thread_id set)."""
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = -1009999
    u.message = AsyncMock()
    u.message.reply_text = AsyncMock()
    u.message.message_thread_id = 42
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
        assert (12345, None) in manager.get_subscribers("news")

    def test_subscribe_duplicate_returns_false(self, manager):
        """Duplicate subscription should return False."""
        manager.subscribe(12345, "news")
        result = manager.subscribe(12345, "news")
        assert result is False

    def test_subscribe_duplicate_no_duplicate_record(self, manager):
        """Duplicate subscription should not create duplicate records."""
        manager.subscribe(12345, "news")
        manager.subscribe(12345, "news")
        assert manager.get_subscribers("news") == [(12345, None)]

    def test_subscribe_multiple_users(self, manager):
        """Multiple different users can subscribe."""
        manager.subscribe(111, "news")
        manager.subscribe(222, "news")
        assert set(manager.get_subscribers("news")) == {(111, None), (222, None)}

    def test_subscribe_different_channels(self, manager):
        """Subscribing to different channels works independently."""
        manager.subscribe(12345, "news")
        manager.subscribe(12345, "threads")
        assert (12345, None) in manager.get_subscribers("news")
        assert (12345, None) in manager.get_subscribers("threads")

    def test_subscribe_stores_timestamp(self, manager):
        """Subscription entry should have a subscribed_at timestamp."""
        manager.subscribe(12345, "news")
        entry = manager._data["news"][0]
        assert "subscribed_at" in entry
        assert "T" in entry["subscribed_at"]  # ISO format


class TestThreadId:
    """Tests for (chat_id, thread_id) composite-key subscriptions (group topics)."""

    def test_subscribe_with_thread_id(self, manager):
        """Subscribing with a thread_id records that specific topic."""
        result = manager.subscribe(12345, "news", thread_id=7)
        assert result is True
        assert (12345, 7) in manager.get_subscribers("news")

    def test_same_chat_different_threads_are_distinct(self, manager):
        """Same chat can subscribe in different topics independently."""
        manager.subscribe(12345, "news", thread_id=7)
        manager.subscribe(12345, "news", thread_id=8)
        subs = manager.get_subscribers("news")
        assert (12345, 7) in subs
        assert (12345, 8) in subs
        assert len(subs) == 2

    def test_thread_none_and_thread_id_are_distinct(self, manager):
        """A General-chat subscription (None) is distinct from a topic one."""
        manager.subscribe(12345, "news")  # thread_id defaults to None
        manager.subscribe(12345, "news", thread_id=7)
        subs = manager.get_subscribers("news")
        assert (12345, None) in subs
        assert (12345, 7) in subs
        assert len(subs) == 2

    def test_subscribe_duplicate_same_thread_returns_false(self, manager):
        """Re-subscribing the same (chat, thread) returns False."""
        manager.subscribe(12345, "news", thread_id=7)
        assert manager.subscribe(12345, "news", thread_id=7) is False

    def test_unsubscribe_specific_thread(self, manager):
        """Unsubscribing one topic leaves the other topics intact."""
        manager.subscribe(12345, "news", thread_id=7)
        manager.subscribe(12345, "news", thread_id=8)
        assert manager.unsubscribe(12345, "news", thread_id=7) is True
        subs = manager.get_subscribers("news")
        assert (12345, 7) not in subs
        assert (12345, 8) in subs

    def test_unsubscribe_thread_none_leaves_topic(self, manager):
        """Unsubscribing the General subscription leaves a topic subscription."""
        manager.subscribe(12345, "news")
        manager.subscribe(12345, "news", thread_id=7)
        assert manager.unsubscribe(12345, "news") is True
        subs = manager.get_subscribers("news")
        assert (12345, None) not in subs
        assert (12345, 7) in subs

    def test_get_subscribers_returns_chat_thread_tuples(self, manager):
        """get_subscribers returns (chat_id, thread_id) tuples."""
        manager.subscribe(111, "threads")
        manager.subscribe(222, "threads", thread_id=3)
        subs = manager.get_subscribers("threads")
        assert (111, None) in subs
        assert (222, 3) in subs

    def test_legacy_entry_without_thread_id_loads_as_none(self, tmp_path):
        """A pre-existing entry without a thread_id field is treated as None."""
        path = tmp_path / "subscriptions.json"
        legacy = {
            "news": [{"chat_id": 999, "subscribed_at": "2026-01-01T00:00:00+00:00"}],
            "threads": [],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        m = SubscriptionManager(path=str(path))
        assert (999, None) in m.get_subscribers("news")

    def test_legacy_entry_dedup_against_thread_none(self, tmp_path):
        """Subscribing (chat, None) when a legacy chat-only entry exists is a dup."""
        path = tmp_path / "subscriptions.json"
        legacy = {
            "news": [{"chat_id": 999, "subscribed_at": "2026-01-01T00:00:00+00:00"}],
            "threads": [],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")
        m = SubscriptionManager(path=str(path))
        assert m.subscribe(999, "news") is False

    def test_subscribe_stores_thread_id_field(self, manager):
        """Persisted entry carries the thread_id field."""
        manager.subscribe(12345, "news", thread_id=7)
        entry = manager._data["news"][0]
        assert entry["thread_id"] == 7


class TestUnsubscribe:
    """Tests for SubscriptionManager.unsubscribe."""

    def test_unsubscribe_removes_entry(self, manager):
        """Unsubscribing should remove the entry and return True."""
        manager.subscribe(12345, "news")
        result = manager.unsubscribe(12345, "news")
        assert result is True
        assert (12345, None) not in manager.get_subscribers("news")

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
        assert manager.get_subscribers("news") == [(222, None)]


class TestGetSubscribers:
    """Tests for SubscriptionManager.get_subscribers."""

    def test_get_subscribers_empty_channel(self, manager):
        """Empty channel returns empty list."""
        assert manager.get_subscribers("news") == []

    def test_get_subscribers_unknown_channel(self, manager):
        """Unknown channel returns empty list."""
        assert manager.get_subscribers("nonexistent") == []

    def test_get_subscribers_returns_chat_ids(self, manager):
        """Should return (chat_id, thread_id) tuples."""
        manager.subscribe(111, "threads")
        manager.subscribe(222, "threads")
        result = manager.get_subscribers("threads")
        assert result == [(111, None), (222, None)]


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
        assert (12345, None) in m2.get_subscribers("news")
        assert (67890, None) in m2.get_subscribers("threads")

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
        assert (12345, None) in m.get_subscribers("news")

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
        mock_manager.subscribe.assert_called_once_with(12345, "news", thread_id=None)
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
        mock_manager.unsubscribe.assert_called_once_with(12345, "news", thread_id=None)
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
        mock_manager.subscribe.assert_called_once_with(12345, "threads", thread_id=None)
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
        mock_manager.unsubscribe.assert_called_once_with(12345, "threads", thread_id=None)
        update.message.reply_text.assert_called_once_with("✅ 已取消 Threads 推播")


@pytest.mark.asyncio
async def test_sub_uanalyze_handler_new(update, context):
    """sub_ua_reports subscribes to the uanalyze channel."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = True
        await sub_uanalyze_handler(update, context)
        mock_manager.subscribe.assert_called_once_with(12345, "uanalyze", thread_id=None)
        update.message.reply_text.assert_called_once_with("✅ 已訂閱 UAnalyze 新報告推播")


@pytest.mark.asyncio
async def test_sub_uanalyze_handler_already(update, context):
    """sub_ua_reports replies info if already subscribed."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = False
        await sub_uanalyze_handler(update, context)
        update.message.reply_text.assert_called_once_with("ℹ️ 您已經訂閱 UAnalyze 新報告推播")


@pytest.mark.asyncio
async def test_unsub_uanalyze_handler_success(update, context):
    """unsub_ua_reports unsubscribes from the uanalyze channel."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.unsubscribe.return_value = True
        await unsub_uanalyze_handler(update, context)
        mock_manager.unsubscribe.assert_called_once_with(12345, "uanalyze", thread_id=None)
        update.message.reply_text.assert_called_once_with("✅ 已取消 UAnalyze 新報告推播")


@pytest.mark.asyncio
async def test_sub_news_handler_in_group_topic_passes_thread_id(group_topic_update, context):
    """In a forum topic, sub_news passes the message_thread_id to the manager."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = True
        await sub_news_handler(group_topic_update, context)
        mock_manager.subscribe.assert_called_once_with(-1009999, "news", thread_id=42)


@pytest.mark.asyncio
async def test_sub_news_handler_private_chat_thread_none(update, context):
    """In a private chat (no topic), sub_news subscribes with thread_id=None."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.subscribe.return_value = True
        await sub_news_handler(update, context)
        mock_manager.subscribe.assert_called_once_with(12345, "news", thread_id=None)


@pytest.mark.asyncio
async def test_unsub_news_handler_in_group_topic_passes_thread_id(group_topic_update, context):
    """In a forum topic, unsub_news passes the message_thread_id to the manager."""
    with patch("bot.subscriptions.manager") as mock_manager:
        mock_manager.unsubscribe.return_value = True
        await unsub_news_handler(group_topic_update, context)
        mock_manager.unsubscribe.assert_called_once_with(-1009999, "news", thread_id=42)


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
async def test_news_now_handler_shows_menu(update, news_context):
    """/news replies with a source-selection inline keyboard (no fetch yet)."""
    await news_now_handler(update, news_context)
    kwargs = update.message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs
    assert "來源" in update.message.reply_text.call_args[0][0]


def _make_news_callback_update(data: str):
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_news_callback_all_sources(news_context):
    """Selecting 全部來源 fetches and shows a diversified list."""
    fake = {"articles": [
        {"title": "台積電創新高", "source": "CNYES", "url": "https://x/1"},
        {"title": "聯發科法說", "source": "MoneyDJ", "url": "https://x/2"},
    ]}
    update = _make_news_callback_update("news:all")
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_source_callback(update, news_context)
    last = update.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "台積電創新高" in last and "https://x/1" in last


@pytest.mark.asyncio
async def test_news_callback_single_source_filters(news_context):
    """Selecting a specific source returns only that source's articles."""
    from tools.fetch_news import SOURCES

    fake = {"articles": [
        {"title": "CNYES 新聞", "source": "CNYES", "url": "https://x/1"},
        {"title": "MoneyDJ 新聞", "source": "MoneyDJ", "url": "https://x/2"},
    ]}
    cnyes_idx = next(i for i, s in enumerate(SOURCES) if s["name"] == "CNYES")
    update = _make_news_callback_update(f"news:{cnyes_idx}")
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_source_callback(update, news_context)
    last = update.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "CNYES 新聞" in last
    assert "MoneyDJ 新聞" not in last


@pytest.mark.asyncio
async def test_news_callback_empty(news_context):
    """No articles for the chosen source → friendly notice."""
    update = _make_news_callback_update("news:all")
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": []}):
        await news_source_callback(update, news_context)
    last = update.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "沒有新聞" in last


@pytest.mark.asyncio
async def test_news_callback_fetch_error(news_context):
    """Fetch error is reported to the user."""
    update = _make_news_callback_update("news:all")
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        await news_source_callback(update, news_context)
    last = update.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "錯誤" in last


@pytest.mark.asyncio
async def test_news_callback_uses_agent_summary():
    """Callback uses agent summary when a bridge is available."""
    fake = {"articles": [{"title": "T", "source": "S", "url": "https://x/1"}]}
    bridge = MagicMock()
    bridge.send = AsyncMock(return_value="• [S] 摘要內容\n  └ https://x/1")
    ctx = MagicMock()
    ctx.bot_data = {"agent_bridge": bridge}
    update = _make_news_callback_update("news:all")

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_source_callback(update, ctx)

    bridge.send.assert_awaited_once()
    last = update.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "摘要內容" in last


@pytest.mark.asyncio
async def test_news_callback_agent_fallback():
    """Callback falls back to a plain list if the agent fails."""
    fake = {"articles": [{"title": "標題X", "source": "CNYES", "url": "https://x/1"}]}
    bridge = MagicMock()
    bridge.send = AsyncMock(side_effect=TimeoutError())
    ctx = MagicMock()
    ctx.bot_data = {"agent_bridge": bridge}
    update = _make_news_callback_update("news:all")

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_source_callback(update, ctx)

    last = update.callback_query.edit_message_text.call_args_list[-1][0][0]
    assert "標題X" in last and "https://x/1" in last


@pytest.mark.asyncio
async def test_news_callback_result_has_back_button(news_context):
    """The news result carries a '返回' button to reopen the source menu."""
    fake = {"articles": [{"title": "T", "source": "CNYES", "url": "https://x/1"}]}
    update = _make_news_callback_update("news:all")
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value=fake):
        await news_source_callback(update, news_context)
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"].inline_keyboard
    assert kb[0][0].callback_data == "news:back"


@pytest.mark.asyncio
async def test_news_callback_back_reopens_menu(news_context):
    """Pressing 返回 re-shows the source menu."""
    update = _make_news_callback_update("news:back")
    await news_source_callback(update, news_context)
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    assert "來源" in update.callback_query.edit_message_text.call_args[0][0]


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
