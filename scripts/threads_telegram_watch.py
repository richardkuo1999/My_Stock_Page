#!/usr/bin/env python3
"""
CLI：週期性抓取 Threads 公開檔案並推送到指定 Telegram 聊天室。
核心邏輯在 analysis_bot.services.threads_watch_service；Bot 內請用 /threads 指令。

執行（專案根目錄）：
  PYTHONPATH=. uv run python scripts/threads_telegram_watch.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

from telegram import Bot

from analysis_bot.services.threads_watch_service import (
    MAX_SEEN_IDS,
    ThreadPost,
    fetch_posts_playwright,
    format_message,
    load_state,
    pick_new_posts,
    save_state,
)

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    if load_dotenv:
        load_dotenv(_REPO_ROOT / ".env", override=False)


async def send_posts(
    token: str,
    chat_id: str,
    username: str,
    new_posts: list[ThreadPost],
    dry_run: bool,
) -> None:
    if dry_run:
        for p in new_posts:
            print("--- dry-run ---")
            print(format_message(username, p)[:500], "...\n")
        return
    bot = Bot(token=token)
    for post in new_posts:
        await bot.send_message(
            chat_id=chat_id,
            text=format_message(username, post),
            disable_web_page_preview=False,
        )
        await asyncio.sleep(0.6)


def resolve_chat_id() -> str:
    return (os.environ.get("THREADS_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="監控 Threads 公開檔案並推送到 Telegram")
    parser.add_argument(
        "--username",
        default=os.environ.get("THREADS_USERNAME", "").lstrip("@"),
        help="Threads 使用者名稱（不含 @）",
    )
    parser.add_argument("--url", default="", help="完整檔案網址（優先於 --username）")
    parser.add_argument(
        "--state",
        type=Path,
        default=_REPO_ROOT / "data" / "threads_watch_state.json",
        help="已見過貼文 id 的 JSON",
    )
    parser.add_argument("--timeout", type=int, default=90000, help="Playwright 逾時（毫秒）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    _load_dotenv()

    username = (args.username or "").strip().lstrip("@")
    profile_url = args.url.strip()
    if not profile_url:
        if not username:
            logger.error("請提供 --username 或 THREADS_USERNAME，或 --url")
            return 2
        profile_url = f"https://www.threads.com/@{username}"
    else:
        m = re.search(r"threads\.com/@([^/?#]+)", profile_url)
        username = m.group(1) if m else username or "unknown"

    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = resolve_chat_id()
    if not args.dry_run and not args.bootstrap:
        if not token:
            logger.error("缺少 TELEGRAM_TOKEN")
            return 2
        if not chat_id:
            logger.error("缺少 TELEGRAM_CHAT_ID 或 THREADS_TELEGRAM_CHAT_ID")
            return 2

    try:
        posts = fetch_posts_playwright(profile_url, args.timeout)
    except Exception as e:
        logger.error("抓取失敗: %s", e)
        return 1

    if not posts:
        logger.warning("未取得任何貼文連結")
        return 1

    state = load_state(args.state)
    seen: set[str] = set(str(x) for x in state.get("seen_ids", []))
    fresh = pick_new_posts(posts, seen)

    if args.bootstrap:
        state["seen_ids"] = [p.post_id for p in posts][-MAX_SEEN_IDS:]
        state["last_username"] = username
        save_state(args.state, state)
        logger.info("bootstrap 完成：已記錄 %s 則貼文 id", len(posts))
        return 0

    if not fresh:
        logger.info("沒有新貼文")
        return 0

    logger.info("發現 %s 則新貼文", len(fresh))
    try:
        asyncio.run(send_posts(token, chat_id, username, fresh, args.dry_run))
    except Exception as e:
        logger.error("Telegram 發送失敗: %s", e)
        return 1

    if args.dry_run:
        logger.info("dry-run：未寫入 state")
        return 0

    for p in fresh:
        seen.add(p.post_id)
    state["seen_ids"] = list(seen)[-MAX_SEEN_IDS:]
    state["last_username"] = username
    save_state(args.state, state)
    logger.info("已更新 state：%s", args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
