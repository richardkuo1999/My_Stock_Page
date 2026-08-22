"""Tests for bot/scheduler.py — news push scheduling."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.scheduler import (
    NEWS_TTL_DAYS,
    SIMILARITY_THRESHOLD,
    THREADS_TTL_DAYS,
    _cleanup_expired,
    _cleanup_expired_threads,
    _format_thread_post,
    _is_duplicate_title,
    _load_pushed_news,
    _load_pushed_threads,
    _save_pushed_news,
    _save_pushed_threads,
    news_push_job,
    setup_scheduler,
    threads_push_job,
    uanalyze_push_job,
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
    assert len(jobs) == 3
    news_job = next(j for j in jobs if j.id == "news_push")
    # Interval trigger
    trigger = news_job.trigger
    assert trigger.interval == timedelta(minutes=60)


def test_setup_scheduler_custom_interval():
    """Scheduler uses interval from config.json."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {"news_schedule_interval_min": 30})
    jobs = scheduler.get_jobs()
    news_job = next(j for j in jobs if j.id == "news_push")
    trigger = news_job.trigger
    assert trigger.interval == timedelta(minutes=30)


def test_setup_scheduler_misfire_grace():
    """Job has misfire_grace_time set."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {})
    jobs = scheduler.get_jobs()
    news_job = next(j for j in jobs if j.id == "news_push")
    assert news_job.misfire_grace_time == 300


# ============================================================
# Threads push job tests
# ============================================================


@pytest.fixture
def pushed_threads_path(tmp_path):
    """Patch PUSHED_THREADS_PATH to use tmp_path."""
    path = tmp_path / "pushed_threads.json"
    with patch("bot.scheduler.PUSHED_THREADS_PATH", path):
        yield path


@pytest.fixture
def sample_thread_posts():
    """Sample thread posts as returned by fetch_threads.check_new()."""
    return [
        {"id": "t001", "user": "stock_guru", "text": "台積電今天表現不錯", "timestamp": "2026-08-22T10:00:00", "url": "https://threads.net/@stock_guru/t001"},
        {"id": "t002", "user": "market_watcher", "text": "美股三大指數齊漲", "timestamp": "2026-08-22T09:30:00", "url": "https://threads.net/@market_watcher/t002"},
    ]


# --- _load_pushed_threads ---


def test_load_pushed_threads_empty(pushed_threads_path):
    """File doesn't exist → returns empty list."""
    result = _load_pushed_threads()
    assert result == []


def test_load_pushed_threads_valid(pushed_threads_path):
    """Valid JSON file → returns parsed records."""
    records = [
        {"id": "t001", "pushed_at": "2026-08-22T03:00:00"},
    ]
    pushed_threads_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    result = _load_pushed_threads()
    assert result == records


def test_load_pushed_threads_corrupt_json(pushed_threads_path):
    """Corrupt JSON file → returns empty list."""
    pushed_threads_path.write_text("not valid json {{{", encoding="utf-8")
    result = _load_pushed_threads()
    assert result == []


# --- _save_pushed_threads ---


def test_save_pushed_threads(pushed_threads_path):
    """Writes records correctly and creates parent dir."""
    records = [
        {"id": "t001", "pushed_at": "2026-08-22T03:00:00"},
    ]
    _save_pushed_threads(records)
    assert pushed_threads_path.exists()
    loaded = json.loads(pushed_threads_path.read_text(encoding="utf-8"))
    assert loaded == records


def test_save_pushed_threads_creates_directory(tmp_path):
    """Creates parent directory if it doesn't exist."""
    nested_path = tmp_path / "subdir" / "pushed_threads.json"
    with patch("bot.scheduler.PUSHED_THREADS_PATH", nested_path):
        _save_pushed_threads([{"id": "t001", "pushed_at": "2026-08-22T00:00:00"}])
    assert nested_path.exists()


# --- _cleanup_expired_threads ---


def test_cleanup_expired_threads():
    """Records older than 3 days get removed."""
    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(days=4)).isoformat()
    recent_time = (now - timedelta(days=1)).isoformat()

    records = [
        {"id": "old_post", "pushed_at": old_time},
        {"id": "recent_post", "pushed_at": recent_time},
    ]
    result = _cleanup_expired_threads(records)
    assert len(result) == 1
    assert result[0]["id"] == "recent_post"


def test_cleanup_expired_threads_keeps_recent():
    """Records within 3 days are kept."""
    now = datetime.now(timezone.utc)
    times = [(now - timedelta(days=i)).isoformat() for i in range(3)]
    records = [{"id": f"post_{i}", "pushed_at": t} for i, t in enumerate(times)]
    result = _cleanup_expired_threads(records)
    assert len(result) == 3


def test_cleanup_expired_threads_naive_datetime():
    """Records with naive datetime (no timezone) treated as UTC."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    records = [{"id": "t_naive", "pushed_at": recent}]
    result = _cleanup_expired_threads(records)
    assert len(result) == 1


def test_cleanup_expired_threads_skips_invalid():
    """Records without valid pushed_at are dropped."""
    records = [
        {"id": "no_date"},
        {"id": "bad_date", "pushed_at": "not-a-date"},
    ]
    result = _cleanup_expired_threads(records)
    assert result == []


# --- _format_thread_post ---


def test_format_thread_post():
    """Verify output format for a normal post."""
    post = {
        "id": "t001",
        "user": "stock_guru",
        "text": "台積電今天表現不錯",
        "timestamp": "2026-08-22T10:00:00",
        "url": "https://threads.net/@stock_guru/t001",
    }
    result = _format_thread_post(post)
    assert "🧵 Threads - stock_guru" in result
    assert "(2026-08-22)" in result
    assert "台積電今天表現不錯" in result
    assert "🔗 https://threads.net/@stock_guru/t001" in result


def test_format_thread_post_long_text():
    """Long text is truncated at 500 chars."""
    long_text = "A" * 600
    post = {
        "id": "t_long",
        "user": "verbose_user",
        "text": long_text,
        "timestamp": "2026-08-22T10:00:00",
        "url": "https://threads.net/@verbose_user/t_long",
    }
    result = _format_thread_post(post)
    # 497 chars + "..." = 500
    assert "A" * 497 + "..." in result
    assert "A" * 498 not in result


def test_format_thread_post_no_url():
    """Post without URL omits the link line."""
    post = {"id": "t_nourl", "user": "someone", "text": "Hello", "timestamp": "", "url": ""}
    result = _format_thread_post(post)
    assert "🔗" not in result
    assert "Hello" in result


def test_format_thread_post_no_text():
    """Post without text omits the text line."""
    post = {"id": "t_notext", "user": "someone", "text": "", "timestamp": "2026-08-22T10:00:00", "url": "https://example.com"}
    result = _format_thread_post(post)
    lines = result.strip().split("\n")
    assert lines[0].startswith("🧵 Threads - someone")
    assert lines[1] == "🔗 https://example.com"


# --- threads_push_job ---


@pytest.mark.asyncio
async def test_threads_push_job_no_posts(mock_bot, mock_subscription_manager, pushed_threads_path):
    """When check_new() returns no posts, nothing is pushed."""
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"posts": []}):
        await threads_push_job(mock_bot, mock_subscription_manager)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_threads_push_job_error_response(mock_bot, mock_subscription_manager, pushed_threads_path):
    """When check_new() returns an error, job exits gracefully."""
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"error": "Token expired"}):
        await threads_push_job(mock_bot, mock_subscription_manager)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_threads_push_job_fetch_exception(mock_bot, mock_subscription_manager, pushed_threads_path):
    """When check_new() raises, job exits gracefully."""
    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, side_effect=Exception("Network error")):
        await threads_push_job(mock_bot, mock_subscription_manager)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_threads_push_job_all_pushed(
    mock_bot, mock_subscription_manager, pushed_threads_path, sample_thread_posts
):
    """When all posts already pushed, nothing new is sent."""
    now = datetime.now(timezone.utc).isoformat()
    pushed_records = [{"id": p["id"], "pushed_at": now} for p in sample_thread_posts]
    pushed_threads_path.write_text(json.dumps(pushed_records), encoding="utf-8")

    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"posts": sample_thread_posts}):
        await threads_push_job(mock_bot, mock_subscription_manager)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_threads_push_job_success(
    mock_bot, mock_subscription_manager, pushed_threads_path, sample_thread_posts
):
    """New posts are formatted and pushed to subscribers."""
    mock_subscription_manager.get_subscribers = MagicMock(return_value=[12345, 67890])

    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"posts": sample_thread_posts}):
        await threads_push_job(mock_bot, mock_subscription_manager)

    # 2 posts × 2 subscribers = 4 sends
    assert mock_bot.send_message.call_count == 4

    # Verify message content
    first_call_text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "🧵 Threads" in first_call_text

    # Records written to file
    saved = json.loads(pushed_threads_path.read_text(encoding="utf-8"))
    assert len(saved) == 2
    saved_ids = {r["id"] for r in saved}
    assert "t001" in saved_ids
    assert "t002" in saved_ids


@pytest.mark.asyncio
async def test_threads_push_job_no_subscribers(
    mock_bot, pushed_threads_path, sample_thread_posts
):
    """No subscribers: posts recorded but not pushed."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[])

    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"posts": sample_thread_posts}):
        await threads_push_job(mock_bot, mgr)

    mock_bot.send_message.assert_not_called()

    # Posts still recorded as pushed
    saved = json.loads(pushed_threads_path.read_text(encoding="utf-8"))
    assert len(saved) == 2


@pytest.mark.asyncio
async def test_threads_push_job_cleans_expired(
    mock_bot, mock_subscription_manager, pushed_threads_path, sample_thread_posts
):
    """Old records are cleaned during job run."""
    old_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    old_records = [{"id": "old_thread", "pushed_at": old_time}]
    pushed_threads_path.write_text(json.dumps(old_records), encoding="utf-8")

    mock_subscription_manager.get_subscribers = MagicMock(return_value=[12345])

    with patch("tools.fetch_threads.check_new", new_callable=AsyncMock, return_value={"posts": sample_thread_posts}):
        await threads_push_job(mock_bot, mock_subscription_manager)

    saved = json.loads(pushed_threads_path.read_text(encoding="utf-8"))
    saved_ids = {r["id"] for r in saved}
    assert "old_thread" not in saved_ids
    assert "t001" in saved_ids
    assert "t002" in saved_ids


# --- setup_scheduler with threads job ---


def test_setup_scheduler_both_jobs():
    """Both news and threads jobs are registered in the scheduler."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {})
    jobs = scheduler.get_jobs()
    job_ids = {j.id for j in jobs}
    assert "news_push" in job_ids
    assert "threads_push" in job_ids
    assert "uanalyze_push" in job_ids
    assert len(jobs) == 3


def test_setup_scheduler_threads_default_interval():
    """Threads job uses default 15-min interval when not in config."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {})
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert jobs["threads_push"].trigger.interval == timedelta(minutes=15)


def test_setup_scheduler_threads_custom_interval():
    """Threads job uses interval from config."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {"threads_schedule_interval_min": 30})
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert jobs["threads_push"].trigger.interval == timedelta(minutes=30)


def test_setup_scheduler_threads_misfire_grace():
    """Threads job has misfire_grace_time set to 120."""
    bot = MagicMock()
    mgr = MagicMock()
    bridge = MagicMock()

    scheduler = setup_scheduler(bot, mgr, bridge, {})
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert jobs["threads_push"].misfire_grace_time == 120


# ============================================================
# UAnalyze report monitor push job tests
# ============================================================


@pytest.fixture
def pushed_uanalyze_path(tmp_path):
    """Patch PUSHED_UANALYZE_PATH to use tmp_path."""
    path = tmp_path / "pushed_uanalyze.json"
    with patch("bot.scheduler.PUSHED_UANALYZE_PATH", path):
        yield path


@pytest.fixture
def sample_reports():
    """Sample reports as returned by uanalyze.list_latest_reports()."""
    return [
        {"id": 102, "title": "台積電 Q3 法說", "stock_name": "台積電", "date": "2024-10-15", "summary": "毛利率創高", "url": "https://u/r102"},
        {"id": 101, "title": "聯發科展望", "stock_name": "聯發科", "date": "2024-10-14", "summary": "AI 拉貨", "url": "https://u/r101"},
    ]


def _recent_ts() -> str:
    """A timestamp inside the UAnalyze TTL window (so seeded state survives cleanup)."""
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_uanalyze_push_first_run_seeds_state(
    mock_bot, pushed_uanalyze_path, sample_reports
):
    """First run (no state): seeds dedup state, pushes nothing (no spam)."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[111])

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}):
        await uanalyze_push_job(mock_bot, mgr)

    mock_bot.send_message.assert_not_called()
    saved = json.loads(pushed_uanalyze_path.read_text(encoding="utf-8"))
    assert {r["id"] for r in saved} == {101, 102}


@pytest.mark.asyncio
async def test_uanalyze_push_new_report(
    mock_bot, pushed_uanalyze_path, sample_reports
):
    """A newly-appeared report id is pushed to subscribers."""
    # Seed state with only the older report.
    pushed_uanalyze_path.write_text(
        json.dumps([{"id": 101, "pushed_at": _recent_ts()}]),
        encoding="utf-8",
    )
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[111, 222])

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}):
        await uanalyze_push_job(mock_bot, mgr)

    # New report 102 pushed to both subscribers.
    assert mock_bot.send_message.call_count == 2
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "台積電" in text and "https://u/r102" in text
    saved = json.loads(pushed_uanalyze_path.read_text(encoding="utf-8"))
    assert {r["id"] for r in saved} == {101, 102}


@pytest.mark.asyncio
async def test_uanalyze_push_no_new(mock_bot, pushed_uanalyze_path, sample_reports):
    """All reports already pushed → nothing sent."""
    pushed_uanalyze_path.write_text(
        json.dumps([
            {"id": 101, "pushed_at": _recent_ts()},
            {"id": 102, "pushed_at": _recent_ts()},
        ]),
        encoding="utf-8",
    )
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[111])

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}):
        await uanalyze_push_job(mock_bot, mgr)

    mock_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_uanalyze_push_no_subscribers(
    mock_bot, pushed_uanalyze_path, sample_reports
):
    """No subscribers: new report recorded as pushed but not sent."""
    pushed_uanalyze_path.write_text(
        json.dumps([{"id": 101, "pushed_at": _recent_ts()}]),
        encoding="utf-8",
    )
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[])

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}):
        await uanalyze_push_job(mock_bot, mgr)

    mock_bot.send_message.assert_not_called()
    saved = json.loads(pushed_uanalyze_path.read_text(encoding="utf-8"))
    assert {r["id"] for r in saved} == {101, 102}


@pytest.mark.asyncio
async def test_uanalyze_push_fetch_error(mock_bot, pushed_uanalyze_path):
    """Fetch error → job returns quietly, nothing pushed."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[111])

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"error": "boom"}):
        await uanalyze_push_job(mock_bot, mgr)

    mock_bot.send_message.assert_not_called()


def test_setup_scheduler_registers_uanalyze_job():
    """setup_scheduler wires a uanalyze_push job with configured interval."""
    scheduler = setup_scheduler(
        MagicMock(), MagicMock(), MagicMock(), {"uanalyze_schedule_interval_min": 45}
    )
    job = next(j for j in scheduler.get_jobs() if j.id == "uanalyze_push")
    assert job.trigger.interval == timedelta(minutes=45)
