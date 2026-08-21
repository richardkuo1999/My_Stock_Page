"""fetch_threads — 抓追蹤帳號 Threads 貼文
用法: python tools/fetch_threads.py --check-new
回傳: JSON {"posts": [{id, user, text, timestamp, url}]}
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

THREADS_API_BASE = "https://graph.threads.net/v1.0"
DEFAULT_TIMEOUT = 15.0
CONFIG_PATH = Path("config.json")


def _get_access_token() -> str | None:
    return os.getenv("THREADS_ACCESS_TOKEN", "").strip() or None


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


async def _fetch_user_threads(user_id: str, token: str) -> list[dict]:
    """Fetch threads for a specific user ID."""
    url = f"{THREADS_API_BASE}/{user_id}/threads"
    params = {
        "fields": "id,text,timestamp,permalink",
        "access_token": token,
        "limit": 10,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, params=params)
        if r.status_code == 401 or r.status_code == 190:
            raise PermissionError("Threads token 已過期，請重新獲取 access token")
        if r.status_code != 200:
            logger.warning("Threads API %s: HTTP %d", user_id, r.status_code)
            return []
        data = r.json()
        posts = []
        for item in data.get("data", []):
            posts.append({
                "id": item.get("id", ""),
                "user": user_id,
                "text": item.get("text", ""),
                "timestamp": item.get("timestamp", ""),
                "url": item.get("permalink", ""),
            })
        return posts


async def _get_me(token: str) -> dict | None:
    """Get authenticated user's profile."""
    url = f"{THREADS_API_BASE}/me"
    params = {"fields": "id,username", "access_token": token}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(url, params=params)
        if r.status_code == 200:
            return r.json()
    return None


async def check_new() -> dict:
    """Fetch latest threads from tracked accounts.

    Returns:
        dict with 'posts' key containing list of post dicts,
        or 'error' key on failure.
    """
    token = _get_access_token()
    if not token:
        return {"error": "THREADS_ACCESS_TOKEN 未設定"}

    config = _load_config()
    user_ids = config.get("threads_users", [])

    # If no tracked users configured, try fetching own threads
    if not user_ids:
        me = await _get_me(token)
        if me and me.get("id"):
            user_ids = [me["id"]]
        else:
            return {"error": "未設定 threads_users 且無法取得自身 ID"}

    all_posts = []
    for user_id in user_ids:
        try:
            posts = await _fetch_user_threads(user_id, token)
            all_posts.extend(posts)
        except PermissionError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.warning("Failed to fetch threads for %s: %s", user_id, e)

    # Sort by timestamp desc
    all_posts.sort(key=lambda p: p.get("timestamp", ""), reverse=True)
    return {"posts": all_posts}


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check-new" not in args and not args:
        print(json.dumps({"error": "用法: python tools/fetch_threads.py --check-new"}, ensure_ascii=False))
        sys.exit(1)

    result = asyncio.run(check_new())
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
