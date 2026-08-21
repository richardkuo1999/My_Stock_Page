"""Tests for bot/logging_conf.py and bot/error_notify.py."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import AsyncMock, patch

import pytest

from bot.error_notify import JobErrorNotifier, run_with_retry
from bot.logging_conf import LOG_DIR, setup_logging


# ============================================================
# Logging configuration tests
# ============================================================


class TestSetupLogging:
    """Tests for setup_logging()."""

    def test_setup_logging_creates_dir(self, tmp_path):
        """Verify data/logs/ directory is created."""
        log_dir = tmp_path / "data" / "logs"
        log_file = log_dir / "bot.log"

        with (
            patch("bot.logging_conf.LOG_DIR", log_dir),
            patch("bot.logging_conf.LOG_FILE", log_file),
        ):
            setup_logging()

        assert log_dir.exists()

    def test_setup_logging_handlers(self, tmp_path):
        """Verify console (INFO) + file (WARNING) handlers are added."""
        log_dir = tmp_path / "data" / "logs"
        log_file = log_dir / "bot.log"

        root = logging.getLogger()
        original_handlers = root.handlers.copy()

        with (
            patch("bot.logging_conf.LOG_DIR", log_dir),
            patch("bot.logging_conf.LOG_FILE", log_file),
        ):
            setup_logging()

        try:
            assert root.level == logging.DEBUG

            # Find console and file handlers
            stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)]
            file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]

            assert len(stream_handlers) >= 1
            assert len(file_handlers) >= 1

            assert stream_handlers[0].level == logging.INFO
            assert file_handlers[0].level == logging.WARNING
        finally:
            # Restore original handlers to avoid test pollution
            root.handlers = original_handlers

    def test_setup_logging_file_rotation_config(self, tmp_path):
        """Verify file handler has correct rotation parameters."""
        log_dir = tmp_path / "data" / "logs"
        log_file = log_dir / "bot.log"

        root = logging.getLogger()
        original_handlers = root.handlers.copy()

        with (
            patch("bot.logging_conf.LOG_DIR", log_dir),
            patch("bot.logging_conf.LOG_FILE", log_file),
        ):
            setup_logging()

        try:
            file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
            assert len(file_handlers) >= 1
            fh = file_handlers[0]
            assert fh.maxBytes == 5 * 1024 * 1024
            assert fh.backupCount == 5
        finally:
            root.handlers = original_handlers


# ============================================================
# JobErrorNotifier tests
# ============================================================


class TestJobErrorNotifier:
    """Tests for JobErrorNotifier."""

    def test_record_success_resets_count(self):
        """record_success sets failure count to 0."""
        notifier = JobErrorNotifier()
        notifier.failure_counts["test_job"] = 5
        notifier.record_success("test_job")
        assert notifier.failure_counts["test_job"] == 0

    def test_record_failure_increments(self):
        """record_failure increments and returns new count."""
        notifier = JobErrorNotifier()
        assert notifier.record_failure("test_job") == 1
        assert notifier.record_failure("test_job") == 2
        assert notifier.record_failure("test_job") == 3

    def test_should_notify_after_retries(self):
        """should_notify returns True after max_retries+1 failures."""
        notifier = JobErrorNotifier(max_retries=2)
        notifier.record_failure("test_job")  # 1
        notifier.record_failure("test_job")  # 2
        assert notifier.should_notify("test_job") is False
        notifier.record_failure("test_job")  # 3 (exceeds max_retries=2)
        assert notifier.should_notify("test_job") is True

    def test_should_not_notify_within_retries(self):
        """should_notify returns False while within retry window."""
        notifier = JobErrorNotifier(max_retries=2)
        notifier.record_failure("test_job")  # 1
        assert notifier.should_notify("test_job") is False
        notifier.record_failure("test_job")  # 2
        assert notifier.should_notify("test_job") is False

    def test_should_notify_unknown_job(self):
        """should_notify returns False for unknown job."""
        notifier = JobErrorNotifier(max_retries=2)
        assert notifier.should_notify("unknown") is False

    @pytest.mark.asyncio
    async def test_notify_admin_sends_message(self):
        """Verifies send_message is called with correct format."""
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "909548136"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        notifier.failure_counts["news_push"] = 3

        await notifier.notify_admin("news_push", "Connection timeout")

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 909548136
        text = call_kwargs["text"]
        assert "news_push" in text
        assert "3" in text
        assert "Connection timeout" in text
        assert "⚠️" in text

    @pytest.mark.asyncio
    async def test_notify_admin_no_bot(self):
        """Does not crash when bot is None."""
        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "909548136"}):
            notifier = JobErrorNotifier(bot=None, max_retries=2)

        notifier.failure_counts["test_job"] = 3
        # Should not raise
        await notifier.notify_admin("test_job", "Some error")

    @pytest.mark.asyncio
    async def test_notify_admin_no_chat_id(self):
        """Does not crash when TELEGRAM_ADMIN_CHAT_ID is empty."""
        mock_bot = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": ""}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        notifier.failure_counts["test_job"] = 3
        # Should not raise
        await notifier.notify_admin("test_job", "Some error")
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_admin_invalid_chat_id(self):
        """Does not crash when TELEGRAM_ADMIN_CHAT_ID is not a number."""
        mock_bot = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "not_a_number"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        notifier.failure_counts["test_job"] = 3
        await notifier.notify_admin("test_job", "Some error")
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_admin_send_failure(self):
        """Does not crash when send_message raises."""
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(side_effect=RuntimeError("Network error"))

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "909548136"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        notifier.failure_counts["test_job"] = 3
        # Should not raise
        await notifier.notify_admin("test_job", "Some error")

    def test_notification_message_format(self):
        """Verify notification message contains required fields."""
        import asyncio

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        notifier.failure_counts["my_job"] = 5

        asyncio.get_event_loop().run_until_complete(
            notifier.notify_admin("my_job", "Something broke badly")
        )

        text = mock_bot.send_message.call_args.kwargs["text"]
        # Must contain job name, error summary, failure count
        assert "my_job" in text
        assert "Something broke badly" in text
        assert "5" in text
        assert "📌 Job:" in text
        assert "❌ 失敗次數:" in text
        assert "📝 錯誤:" in text
        assert "🕒 時間:" in text

    def test_error_truncated_in_message(self):
        """Long error messages are truncated to 200 chars."""
        import asyncio

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        notifier.failure_counts["job"] = 3
        long_error = "X" * 500

        asyncio.get_event_loop().run_until_complete(
            notifier.notify_admin("job", long_error)
        )

        text = mock_bot.send_message.call_args.kwargs["text"]
        # Error should be truncated
        assert "X" * 200 in text
        assert "X" * 201 not in text


# ============================================================
# run_with_retry tests
# ============================================================


class TestRunWithRetry:
    """Tests for run_with_retry()."""

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        """Job succeeds on first try, no notification."""
        mock_job = AsyncMock()
        mock_bot = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        await run_with_retry(mock_job, "test_job", notifier)

        mock_job.assert_called_once()
        assert notifier.failure_counts.get("test_job", 0) == 0
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_after_retry(self):
        """Job fails once then succeeds on retry, no notification."""
        call_count = 0

        async def flaky_job():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Temporary failure")
            return None

        mock_bot = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        await run_with_retry(flaky_job, "test_job", notifier)

        assert call_count == 2
        assert notifier.failure_counts["test_job"] == 0  # Reset on success
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_failures_notifies_admin(self):
        """All retries exhausted → admin notified."""
        mock_job = AsyncMock(side_effect=RuntimeError("Persistent failure"))
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        await run_with_retry(mock_job, "test_job", notifier)

        # 1 initial + 2 retries = 3 attempts
        assert mock_job.call_count == 3
        assert notifier.failure_counts["test_job"] == 3
        mock_bot.send_message.assert_called_once()

        # Verify notification content
        text = mock_bot.send_message.call_args.kwargs["text"]
        assert "test_job" in text
        assert "Persistent failure" in text
        assert "3" in text

    @pytest.mark.asyncio
    async def test_retry_with_args(self):
        """Arguments are correctly passed to job function."""
        received_args = []

        async def job_with_args(a, b, c):
            received_args.extend([a, b, c])

        mock_bot = AsyncMock()
        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=2)

        await run_with_retry(job_with_args, "test_job", notifier, "x", "y", "z")

        assert received_args == ["x", "y", "z"]

    @pytest.mark.asyncio
    async def test_max_retries_1(self):
        """With max_retries=1: 1 initial + 1 retry = 2 attempts max."""
        mock_job = AsyncMock(side_effect=RuntimeError("fail"))
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with patch.dict("os.environ", {"TELEGRAM_ADMIN_CHAT_ID": "12345"}):
            notifier = JobErrorNotifier(bot=mock_bot, max_retries=1)

        await run_with_retry(mock_job, "test_job", notifier)

        assert mock_job.call_count == 2
        assert notifier.failure_counts["test_job"] == 2

    @pytest.mark.asyncio
    async def test_no_notification_without_bot(self):
        """All retries exhausted but no bot → no crash."""
        mock_job = AsyncMock(side_effect=RuntimeError("fail"))

        notifier = JobErrorNotifier(bot=None, max_retries=2)

        await run_with_retry(mock_job, "test_job", notifier)

        assert mock_job.call_count == 3
        assert notifier.failure_counts["test_job"] == 3
