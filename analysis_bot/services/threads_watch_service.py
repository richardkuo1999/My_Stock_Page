"""
Threads 公開檔案監控：Playwright 擷取貼文、格式化 Telegram 訊息。
供 Bot 指令／排程與 scripts/threads_telegram_watch.py 共用。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[misc, assignment]
    PlaywrightTimeout = Exception  # type: ignore[misc, assignment]

try:
    from telegram.constants import MessageLimit
except ImportError:
    MessageLimit = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

MAX_SEEN_IDS = 800
DEFAULT_FETCH_TIMEOUT_MS = 90_000

TG_TEXT_SAFE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class ThreadPost:
    post_id: str
    url: str
    text: str


def pick_new_posts(posts: list[ThreadPost], seen: set[str]) -> list[ThreadPost]:
    """保留頁面順序（通常最新在上），只回傳尚未見過的貼文。"""
    return [p for p in posts if p.post_id not in seen]


def trim_threads_ui_prefix(text: str, *, max_strip_lines: int = 8) -> str:
    """去掉串文卡片開頭的使用者名、相對時間等短行，保留正文。"""
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    stripped = 0
    short_line = re.compile(r"^[\w.@]{1,40}$")
    rel_time = re.compile(r"^(?:\d+天前?|\d+天|\d{1,2}/\d{1,2}/\d{2,4})$")
    for s in lines:
        if not s:
            continue
        if stripped < max_strip_lines and (
            short_line.match(s) or rel_time.match(s) or s in ("翻譯", "Translate")
        ):
            stripped += 1
            continue
        out.append(s)
    return "\n".join(out).strip() or text.strip()


def sanitize_telegram_text(text: str, max_len: int) -> str:
    text = TG_TEXT_SAFE.sub("", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 20].rstrip() + "\n…（已截斷）"


def format_message(username: str, post: ThreadPost) -> str:
    header = f"Threads @{username} 新貼文\n{post.url}\n\n"
    limit = (MessageLimit.MAX_TEXT_LENGTH if MessageLimit else 4096) - len(header) - 4
    body = sanitize_telegram_text(post.text, max(500, limit))
    return header + body


def merge_seen_json(old_json: str, new_ids: Iterable[str]) -> str:
    """合併已見過的 post id，去重並保留尾端 MAX_SEEN_IDS 筆。"""
    try:
        old = json.loads(old_json or "[]")
        if not isinstance(old, list):
            old = []
    except json.JSONDecodeError:
        old = []
    merged: list[str] = list(
        dict.fromkeys([str(x) for x in old if x] + [str(x) for x in new_ids if x])
    )
    return json.dumps(merged[-MAX_SEEN_IDS:], ensure_ascii=False)


EXTRACT_POSTS_JS = r"""
() => {
  function postIdFromHref(href) {
    try {
      const u = new URL(href);
      const parts = u.pathname.split("/").filter(Boolean);
      const i = parts.indexOf("post");
      return i >= 0 && parts[i + 1] ? parts[i + 1] : null;
    } catch (e) {
      return null;
    }
  }
  const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
  const byId = new Map();
  for (const a of anchors) {
    try {
      const u = new URL(a.href);
      const id = postIdFromHref(a.href);
      if (!id || byId.has(id)) continue;
      let node = a;
      let best = "";
      for (let depth = 0; depth < 32 && node; depth++) {
        node = node.parentElement;
        if (!node) break;
        const links = Array.from(node.querySelectorAll('a[href*="/post/"]'));
        const ids = new Set(
          links.map((l) => postIdFromHref(l.href)).filter(Boolean)
        );
        if (ids.size !== 1 || !ids.has(id)) continue;
        const t = (node.innerText || "").trim();
        if (t.length > best.length && t.length < 14000) best = t;
      }
      if (!best) {
        node = a;
        for (let depth = 0; depth < 24 && node; depth++) {
          node = node.parentElement;
          if (!node) break;
          const t = (node.innerText || "").trim();
          if (t.length > best.length && t.length < 14000) best = t;
        }
      }
      const pathParts = u.pathname.split("/").filter(Boolean);
      const pi = pathParts.indexOf("post");
      const base =
        u.origin +
        "/" +
        pathParts.slice(0, pi + 2).join("/");
      byId.set(id, { id, url: base, text: best });
    } catch (e) {}
  }
  return Array.from(byId.values());
}
"""


def fetch_posts_playwright(
    profile_url: str, timeout_ms: int = DEFAULT_FETCH_TIMEOUT_MS
) -> list[ThreadPost]:
    if sync_playwright is None:
        raise RuntimeError(
            "未安裝 playwright。請執行: pip install playwright && playwright install chromium"
        )
    posts: list[ThreadPost] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                locale="zh-TW",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            page.goto(profile_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(4500)
            try:
                page.wait_for_selector('a[href*="/post/"]', timeout=min(15000, timeout_ms // 2))
            except Exception:
                pass
            raw = page.evaluate(EXTRACT_POSTS_JS)
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    pid = str(item.get("id") or "").strip()
                    url = str(item.get("url") or "").strip()
                    text = str(item.get("text") or "").strip()
                    if pid and url:
                        cleaned = trim_threads_ui_prefix(text) if text else ""
                        posts.append(
                            ThreadPost(
                                post_id=pid,
                                url=url,
                                text=cleaned or text or "（無文字內文）",
                            )
                        )
        except PlaywrightTimeout as e:
            raise RuntimeError(f"Threads 頁面載入逾時: {e}") from e
        finally:
            browser.close()
    return posts


# --- CLI 用 state 檔（與 DB 分離）---


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen_ids": [], "version": 1}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("State file unreadable (%s), starting fresh: %s", path, e)
        return {"seen_ids": [], "version": 1}
    if not isinstance(data.get("seen_ids"), list):
        data["seen_ids"] = []
    return data


def save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = [str(x) for x in data.get("seen_ids", []) if x]
    data["seen_ids"] = ids[-MAX_SEEN_IDS:]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
