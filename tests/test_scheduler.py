"""Tests for bot/scheduler.py — news push scheduling."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.scheduler import (
    NEWS_TTL_DAYS,
    SEND_MAX_ATTEMPTS,
    SIMILARITY_THRESHOLD,
    _cleanup_expired,
    _format_uanalyze_report,
    _is_duplicate_title,
    _load_pushed_news,
    _save_pushed_news,
    _send_with_retry,
    news_push_job,
    setup_scheduler,
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
    """Mock SubscriptionManager: one General-thread sub and one forum-topic sub."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[(12345, None), (67890, 7)])
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
    """New articles are listed (title + URL) and pushed to subscribers — no Agent."""
    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    # Agent bridge must NOT be called — push is a plain title + URL list now.
    mock_agent_bridge.send.assert_not_called()

    # Bot sent message to both subscribers
    assert mock_bot.send_message.call_count == 2
    calls = mock_bot.send_message.call_args_list
    assert calls[0].kwargs["chat_id"] == 12345
    assert calls[0].kwargs["message_thread_id"] is None
    assert calls[1].kwargs["chat_id"] == 67890
    assert calls[1].kwargs["message_thread_id"] == 7
    assert "新聞推播" in calls[0].kwargs["text"]
    # Plain list contains source tag + raw URL.
    assert "https://example.com/1" in calls[0].kwargs["text"]

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
async def test_news_push_job_ignores_agent_bridge(
    mock_bot, mock_subscription_manager, pushed_news_path, sample_articles
):
    """Push never calls the Agent, even when a bridge is provided."""
    bridge = AsyncMock()
    bridge.send = AsyncMock()

    with patch("tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}):
        await news_push_job(mock_bot, mock_subscription_manager, bridge)

    bridge.send.assert_not_called()
    # Message still sent as a plain title + URL list.
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
    assert len(jobs) == 4  # news + uanalyze + stock_pool_refresh + log_audit
    news_job = next(j for j in jobs if j.id == "news_push")
    # Interval trigger
    trigger = news_job.trigger
    assert trigger.interval == timedelta(minutes=60)
    # Log audit job registered with default 1440-min (daily) interval.
    audit_job = next(j for j in jobs if j.id == "log_audit")
    assert audit_job.trigger.interval == timedelta(minutes=1440)


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
        {"id": 102, "stock_code": "2330", "stock_name": "台積電", "title": "資本支出", "date": "2024-10-15", "summary": "毛利率創高"},
        {"id": 101, "stock_code": "2454", "stock_name": "聯發科", "title": "近況發展", "date": "2024-10-14", "summary": "AI 拉貨"},
    ]


def _recent_ts() -> str:
    """A timestamp inside the UAnalyze TTL window (so seeded state survives cleanup)."""
    return datetime.now(timezone.utc).isoformat()


def test_format_uanalyze_report_shows_code_name_title():
    """Formatter shows 公司名(代號), 報告主題 and 日期, plus the summary."""
    text = _format_uanalyze_report(
        {"id": 1, "stock_code": "2330", "stock_name": "台積電", "title": "資本支出", "date": "2026-08-21", "summary": "擴產先進製程"}
    )
    assert "台積電 (2330)" in text
    assert "資本支出（2026-08-21）" in text
    assert "擴產先進製程" in text


def test_format_uanalyze_report_missing_fields():
    """Formatter degrades gracefully when code/title/date are missing."""
    text = _format_uanalyze_report({"id": 2, "stock_name": "某股", "summary": "x"})
    assert "某股" in text  # no code → just name, no parens
    assert "(" not in text.split("\n")[0]


@pytest.mark.asyncio
async def test_uanalyze_push_first_run_seeds_state(
    mock_bot, pushed_uanalyze_path, sample_reports
):
    """First run (no state): seeds dedup state, pushes nothing (no spam)."""
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[(111, None)])

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
    mgr.get_subscribers = MagicMock(return_value=[(111, None), (222, 9)])

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}):
        await uanalyze_push_job(mock_bot, mgr)

    # New report 102 pushed to both subscribers.
    assert mock_bot.send_message.call_count == 2
    text = mock_bot.send_message.call_args_list[0].kwargs["text"]
    assert "台積電" in text and "2330" in text and "資本支出" in text
    thread_targets = {
        (c.kwargs["chat_id"], c.kwargs["message_thread_id"])
        for c in mock_bot.send_message.call_args_list
    }
    assert (111, None) in thread_targets
    assert (222, 9) in thread_targets
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
    mgr.get_subscribers = MagicMock(return_value=[(111, None)])

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
    mgr.get_subscribers = MagicMock(return_value=[(111, None)])

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


# ============================================================
# Per-send retry on transient delivery failures
# ============================================================


@pytest.mark.asyncio
async def test_send_with_retry_success_first_try():
    """A successful send returns True with a single attempt."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    ok = await _send_with_retry(bot, chat_id=1, text="hi")
    assert ok is True
    assert bot.send_message.call_count == 1


@pytest.mark.asyncio
async def test_send_with_retry_recovers_after_timeout():
    """Transient TimedOut is retried and succeeds on a later attempt."""
    from telegram.error import TimedOut

    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=[TimedOut("t"), None])
    with patch("bot.scheduler.asyncio.sleep", new_callable=AsyncMock):
        ok = await _send_with_retry(bot, chat_id=1, text="hi")
    assert ok is True
    assert bot.send_message.call_count == 2


@pytest.mark.asyncio
async def test_send_with_retry_gives_up_after_max_attempts():
    """All attempts time out → returns False after SEND_MAX_ATTEMPTS tries."""
    from telegram.error import TimedOut

    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=TimedOut("t"))
    with patch("bot.scheduler.asyncio.sleep", new_callable=AsyncMock):
        ok = await _send_with_retry(bot, chat_id=1, text="hi")
    assert ok is False
    assert bot.send_message.call_count == SEND_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_send_with_retry_non_transient_no_retry():
    """A non-transient error is not retried and returns False."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=ValueError("bad chat"))
    ok = await _send_with_retry(bot, chat_id=1, text="hi")
    assert ok is False
    assert bot.send_message.call_count == 1


@pytest.mark.asyncio
async def test_news_push_all_deliveries_fail_not_marked_pushed(
    mock_bot, mock_subscription_manager, mock_agent_bridge, pushed_news_path, sample_articles
):
    """If every delivery times out, articles are NOT marked as pushed so they
    get retried on the next run instead of being silently dropped."""
    from telegram.error import TimedOut

    mock_bot.send_message = AsyncMock(side_effect=TimedOut("t"))
    with patch("bot.scheduler.asyncio.sleep", new_callable=AsyncMock), patch(
        "tools.fetch_news.latest", new_callable=AsyncMock, return_value={"articles": sample_articles}
    ):
        await news_push_job(mock_bot, mock_subscription_manager, mock_agent_bridge)

    # Nothing recorded as pushed → next run retries.
    assert not pushed_news_path.exists() or json.loads(
        pushed_news_path.read_text(encoding="utf-8")
    ) == []


@pytest.mark.asyncio
async def test_uanalyze_push_all_deliveries_fail_not_marked_pushed(
    mock_bot, pushed_uanalyze_path, sample_reports
):
    """If a report times out to every subscriber, it is NOT marked pushed and is
    retried next run (state keeps only the previously-seeded id)."""
    from telegram.error import TimedOut

    pushed_uanalyze_path.write_text(
        json.dumps([{"id": 101, "pushed_at": _recent_ts()}]),
        encoding="utf-8",
    )
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[(111, None)])
    mock_bot.send_message = AsyncMock(side_effect=TimedOut("t"))

    with patch("bot.scheduler.asyncio.sleep", new_callable=AsyncMock), patch(
        "tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}
    ):
        await uanalyze_push_job(mock_bot, mgr)

    saved = json.loads(pushed_uanalyze_path.read_text(encoding="utf-8"))
    # Report 102 failed → not added; only the seeded 101 remains.
    assert {r["id"] for r in saved} == {101}


@pytest.mark.asyncio
async def test_uanalyze_push_partial_success_marks_only_delivered(
    mock_bot, pushed_uanalyze_path, sample_reports
):
    """A report that succeeds to at least one subscriber is marked pushed."""
    pushed_uanalyze_path.write_text(
        json.dumps([{"id": 101, "pushed_at": _recent_ts()}]),
        encoding="utf-8",
    )
    mgr = MagicMock()
    mgr.get_subscribers = MagicMock(return_value=[(111, None)])
    mock_bot.send_message = AsyncMock()  # succeeds

    with patch("tools.uanalyze.list_latest_reports", new_callable=AsyncMock, return_value={"reports": sample_reports}):
        await uanalyze_push_job(mock_bot, mgr)

    saved = json.loads(pushed_uanalyze_path.read_text(encoding="utf-8"))
    assert {r["id"] for r in saved} == {101, 102}
