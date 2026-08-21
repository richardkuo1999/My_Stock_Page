"""Tests for bot/scheduler.py — news push scheduling."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.scheduler import (
    NEWS_TTL_DAYS,
    SIMILARITY_THRESHOLD,
    _cleanup_expired,
    _is_duplicate_title,
    _load_pushed_news,
    _save_pushed_news,
    news_push_job,
    setup_scheduler,
)


# --- Fixtures ---


@pytest.fixture
def pushed_news_path(tmp_path):
    """Patch PUSHED_NEWS_PATH to use tmp_path."""
    path = tmp_path / "pushed_news.json"
    with patch("bot.scheduler.PUSHED_NEWS_PATH", path):
        yield path


@pytest.fixture
def sample_articles():
    """Sample articles as returned by fetch_news.latest()."""
    return [
        {"title": "台積電法說會：AI需求強勁", "source": "CNYES", "url": "https://example.com/1", "date": "2026-08-22"},
        {"title": "聯發科Q3展望正面", "source": "MoneyDJ", "url": "https://example.com/2", "date": "2026-08-22"},
        {"title": "美股收高 科技股領漲", "source": "Yahoo股市", "url": "https://example.com/3", "date": "2026-08-22"},
    ]


@pytest.fixture
def mock_bot():
    """Mock Telegram bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def mock_subscription_manager():
    """Mock SubscriptionManager."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[12345, 67890])
    return mgr


@pytest.fixture
def mock_agent_bridge():
    """Mock AgentBridge."""
    bridge = AsyncMock()
    bridge.send = AsyncMock(return_value="• [CNYES] 台積電AI需求強\n  └ https://example.com/1")
    return bridge


# --- _load_pushed_news ---


def test_load_pushed_news_empty(pushed_news_path):
    """File doesn't exist → returns empty list."""
    result = _load_pushed_news()
    assert result == []


def test_load_pushed_news_valid(pushed_news_path):
    """Valid JSON file → returns parsed records."""
    records = [
        {"url": "https://example.com/1", "title": "Test", "pushed_at": "2026-08-22T03:00:00"},
    ]
    pushed_news_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    result = _load_pushed_news()
    assert result == records


def test_load_pushed_news_corrupt_json(pushed_news_path):
    """Corrupt JSON file → returns empty list."""
    pushed_news_path.write_text("not valid json {{{", encoding="utf-8")
    result = _load_pushed_news()
    assert result == []


# --- _save_pushed_news ---


def test_save_pushed_news(pushed_news_path):
    """Writes records correctly and creates parent dir."""
    records = [
        {"url": "https://example.com/1", "title": "Test", "pushed_at": "2026-08-22T03:00:00"},
    ]
    _save_pushed_news(records)
    assert pushed_news_path.exists()
    loaded = json.loads(pushed_news_path.read_text(encoding="utf-8"))
    assert loaded == records


def test_save_pushed_news_creates_directory(tmp_path):
    """Creates parent directory if it doesn't exist."""
    nested_path = tmp_path / "subdir" / "pushed_news.json"
    with patch("bot.scheduler.PUSHED_NEWS_PATH", nested_path):
        _save_pushed_news([{"url": "https://x.com", "pushed_at": "2026-08-22T00:00:00"}])
    assert nested_path.exists()


# --- _cleanup_expired ---


def test_cleanup_expired_removes_old():
    """Records older than 7 days get removed."""
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=8)).isoformat()
    recent_time = (now - timedelta(days=1)).isoformat()

    records = [
        {"url": "https://old.com", "title": "Old", "pushed_at": old_time},
        {"url": "https://recent.com", "title": "Recent", "pushed_at": recent_time},
    ]
    result = _cleanup_expired(records)
    assert len(result) == 1
    assert result[0]["url"] == "https://recent.com"


def test_cleanup_keeps_recent():
    """Records within 7 days are kept."""
    now = datetime.now(timezone.utc)
    times = [
        (now - timedelta(days=i)).isoformat() for i in range(7)
    ]
    records = [{"url": f"https://example.com/{i}", "pushed_at": t} for i, t in enumerate(times)]
    result = _cleanup_expired(records)
    assert len(result) == 7


def test_cleanup_expired_handles_naive_datetime():
    """Records with naive datetime (no timezone) treated as UTC."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    records = [{"url": "https://x.com", "pushed_at": recent}]
    result = _cleanup_expired(records)
    assert len(result) == 1


def test_cleanup_expired_skips_invalid_records():
    """Records without valid pushed_at are dropped."""
    records = [
        {"url": "https://x.com"},  # missing pushed_at
        {"url": "https://y.com", "pushed_at": "not-a-date"},  # invalid
    ]
    result = _cleanup_expired(records)
    assert result == []


# --- _is_duplicate_title ---


def test_is_duplicate_title_similar():
    """Highly similar titles are detected as duplicates."""
    existing = ["台積電法說會：AI需求強勁帶動成長"]
    assert _is_duplicate_title("台積電法說會：AI需求強勁帶動成長", existing) is True


def test_is_duplicate_title_slightly_different():
    """Titles with minor differences (>80% similar) are duplicates."""
    existing = ["台積電法說會：AI需求強勁帶動成長"]
    # Same meaning, slightly different wording
    assert _is_duplicate_title("台積電法說會：AI需求強勁帶動成長!", existing) is True


def test_is_not_duplicate_title():
    """Clearly different titles pass through."""
    existing = ["台積電法說會：AI需求強勁帶動成長"]
    assert _is_duplicate_title("聯發科Q3展望正面", existing) is False


def test_is_duplicate_title_empty():
    """Empty title is never a duplicate."""
    existing = ["Some title"]
    assert _is_duplicate_title("", existing) is False


def test_is_duplicate_title_empty_existing():
    """Empty existing titles are skipped."""
    existing = ["", ""]
    assert _is_duplicate_title("Some title", existing) is False


# --- news_push_job ---


@pytest.mark.asyncio
async def test_news_push_job_no_articles(mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path):
    """When latest() returns no articles, nothing is pushed."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": []}):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_news_push_job_all_pushed(
    mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path, sample_articles
):
    """When all articles already pushed, nothing new is sent."""
    now = datetime.now(timezone.utc).isoformat()
    pushed_records = [{"url": a["url"], "title": a["title"], "pushed_at": now} for a in sample_articles]
    pushed_news_path.write_text(json.dumps(pushed_records), encoding="utf-8")

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_news_push_job_success(
    mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path, sample_articles
):
    """New articles are summarized and pushed to subscribers."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    # Agent bridge was called for summarization
    mock_agent_bridge.send.assert_called_once()

    # Bot sent message to both subscribers
    assert mock_bot.send_message.call_count == 2
    calls = mock_bot.send_message.call_args_list
    assert calls[0].kwargs["chat_id"] == 12345
    assert calls[1].kwargs["chat_id"] == 67890
    assert "新聞推播" in calls[0].kwargs["text"]

    # Records written to file
    saved = json.loads(pushed_news_path.read_text(encoding="utf-8"))
    assert len(saved) == 3
    assert saved[0]["url"] == "https://example.com/1"


@pytest.mark.asyncio
async def test_news_push_job_no_subscribers(
    mock_bot, mock_agent_bridge, pushed_news_path, sample_articles
):
    """No subscribers: articles recorded but not pushed."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[])

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mgr, mock_agent_bridge)

    mock_bot.send_message.assert_not_called()
    mock_agent_bridge.send.assert_not_called()

    # Articles still recorded as pushed
    saved = json.loads(pushed_news_path.read_text(encoding="utf-8"))
    assert len(saved) == 3


@pytest.mark.asyncio
async def test_news_push_job_agent_failure_fallback(
    mock_bot, mock_subscription_manager, pushed_news_path, sample_articles
):
    """When agent fails, falls back to simple formatted list."""
    failing_bridge = AsyncMock()
    failing_bridge.send = AsyncMock(side_effect=RuntimeError("Agent down"))

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, failing_bridge)

    # Message still sent (fallback format)
    assert mock_bot.send_message.call_count == 2
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "https://example.com/1" in text
    assert "[CNYES]" in text


@pytest.mark.asyncio
async def test_news_push_job_no_bridge_fallback(
    mock_bot, mock_subscription_manager, pushed_news_path, sample_articles
):
    """When agent_bridge is None, uses simple formatted list."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, None)

    assert mock_bot.send_message.call_count == 2
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "https://example.com/1" in text


@pytest.mark.asyncio
async def test_news_push_job_fetch_failure(
    mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path
):
    """When fetch_news.latest() raises, job exits gracefully."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, side_effect=Exception("Network error")):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_news_push_job_fuzzy_dedup(
    mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path
):
    """Articles with similar titles to already-pushed ones are skipped."""
    now = datetime.now(timezone.utc).isoformat()
    pushed_records = [
        {"url": "https://old-url.com/1", "title": "台積電法說會：AI需求強勁帶動成長", "pushed_at": now},
    ]
    pushed_news_path.write_text(json.dumps(pushed_records), encoding="utf-8")

    # New article with very similar title but different URL
    articles = [
        {"title": "台積電法說會：AI需求強勁帶動成長!", "source": "CNYES", "url": "https://other-url.com/1", "date": "2026-08-22"},
    ]

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": articles}):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    # Fuzzy dedup should filter it out
    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_news_push_job_cleans_expired(
    mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path, sample_articles
):
    """Old records are cleaned during job run."""
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    old_records = [{"url": "https://expired.com/x", "title": "Old news", "pushed_at": old_time}]
    pushed_news_path.write_text(json.dumps(old_records), encoding="utf-8")

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    saved = json.loads(pushed_news_path.read_text(encoding="utf-8"))
    # Old record should be cleaned, only new articles remain
    urls = [r["url"] for r in saved]
    assert "https://expired.com/x" not in urls
    assert len(saved) == 3


# --- setup_scheduler ---


def test_setup_scheduler_default_interval():
    """Scheduler created with default 60-min interval when not in config."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {})
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "news_push"
    # Interval trigger
    trigger = jobs[0].trigger
    assert trigger.interval == timedelta(minutes=60)


def test_setup_scheduler_custom_interval():
    """Scheduler uses interval from config.json."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {"news_schedule_interval_min": 30})
    jobs = scheduler.get_jobs()
    trigger = jobs[0].trigger
    assert trigger.interval == timedelta(minutes=30)


def test_setup_scheduler_misfire_grace():
    """Job has misfire_grace_time set."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {})
    jobs = scheduler.get_jobs()
    assert jobs[0].misfire_grace_time == 300
