"""Error notification for scheduled jobs."""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class JobErrorNotifier:
    """Tracks job failures and sends Telegram alerts on consecutive failures."""

    def __init__(self, bot=None, max_retries: int = 2):
        self.bot = bot
        self.max_retries = max_retries
        self.failure_counts: dict[str, int] = {}  # job_name -> consecutive failures
        self._admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

    @property
    def admin_chat_id(self) -> int | None:
        """Parse admin chat ID from environment variable."""
        try:
            return int(self._admin_chat_id) if self._admin_chat_id else None
        except ValueError:
            return None

    def record_success(self, job_name: str) -> None:
        """Reset failure count on success."""
        self.failure_counts[job_name] = 0

    def record_failure(self, job_name: str) -> int:
        """Increment failure count, return new count."""
        self.failure_counts[job_name] = self.failure_counts.get(job_name, 0) + 1
        return self.failure_counts[job_name]

    def should_notify(self, job_name: str) -> bool:
        """True if failures exceed max_retries (i.e., retries exhausted)."""
        return self.failure_counts.get(job_name, 0) > self.max_retries

    async def notify_admin(self, job_name: str, error: str) -> None:
        """Send failure notification to admin via Telegram."""
        if not self.bot or not self.admin_chat_id:
            logger.warning(
                "Cannot notify admin: bot=%s, chat_id=%s",
                bool(self.bot),
                self.admin_chat_id,
            )
            return

        count = self.failure_counts.get(job_name, 0)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        message = (
            f"⚠️ 排程 Job 連續失敗\n\n"
            f"📌 Job: {job_name}\n"
            f"❌ 失敗次數: {count}\n"
            f"📝 錯誤: {error[:200]}\n"
            f"🕒 時間: {now}"
        )

        try:
            await self.bot.send_message(chat_id=self.admin_chat_id, text=message)
            logger.info("Admin notified about %s failure", job_name)
        except Exception as e:
            logger.error("Failed to notify admin: %s", e)


async def run_with_retry(job_fn, job_name: str, notifier: JobErrorNotifier, *args) -> None:
    """Run a job with retry and error notification.

    Attempts the job once, then retries up to notifier.max_retries times.
    If all attempts fail and retries are exhausted, notifies admin.
    """
    for attempt in range(1, notifier.max_retries + 2):  # 1 initial + max_retries
        try:
            await job_fn(*args)
            notifier.record_success(job_name)
            return
        except Exception as e:
            notifier.record_failure(job_name)
            logger.warning("Job %s attempt %d failed: %s", job_name, attempt, e)
            if attempt <= notifier.max_retries:
                continue  # retry
            # All retries exhausted
            if notifier.should_notify(job_name):
                await notifier.notify_admin(job_name, str(e))
            break
