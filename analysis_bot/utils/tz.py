"""台灣時區工具。"""

from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))


def now_tw() -> datetime:
    """回傳台灣時區的當前時間。"""
    return datetime.now(TW_TZ)
