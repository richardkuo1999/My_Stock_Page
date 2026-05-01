"""
Google Sheets 自選股同步服務。

定時抓取用戶註冊的 Google Sheets，解析持股清單，
同步到 WatchlistEntry（以 note 欄位合併狀態/策略等資訊）。
有變更時推播 Telegram 通知。

試算表格式（預期欄位順序）：
  B: 股票代號, C: 股票名稱, D: 新增日期, E: 狀態, F: 週期,
  G: 備註&策略, H: 現價, I: 參考損, J: 月成本, K: 持倉%, L: 近期動作
"""

import asyncio
import csv
import hashlib
import io
import logging
import re
from datetime import datetime

import httpx
from sqlmodel import Session, select

from ..config import get_settings
from ..database import engine
from ..models.gsheet_sub import GSheetSubscription
from ..models.watchlist import WatchlistEntry

logger = logging.getLogger(__name__)


def _build_csv_url(spreadsheet_id: str, gid: str) -> str:
    """Build the public CSV export URL for a specific sheet tab."""
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/export?format=csv&gid={gid}"
    )


def _parse_sheet_url(url: str) -> tuple[str, str]:
    """
    Extract spreadsheet_id and gid from a Google Sheets URL.
    """
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        raise ValueError(f"Cannot parse spreadsheet ID from URL: {url}")
    sheet_id = m.group(1)

    gid = "0"
    gid_match = re.search(r"[?&#]gid=(\d+)", url)
    if gid_match:
        gid = gid_match.group(1)

    return sheet_id, gid


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def fetch_sheet_csv(spreadsheet_id: str, gid: str) -> str | None:
    """Fetch CSV content from Google Sheets public export."""
    url = _build_csv_url(spreadsheet_id, gid)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPStatusError as e:
        logger.error("Google Sheets fetch failed (HTTP %d): %s", e.response.status_code, url)
        return None
    except Exception as e:
        logger.error("Google Sheets fetch error: %s", e)
        return None


def _extract_preview(csv_text: str, max_rows: int = 5) -> list[list[str]]:
    """Extract first N rows from CSV text for notification preview."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(row)
    return rows


def _parse_price(val: str) -> float | None:
    """Parse price string like '1,140.0' to float."""
    if not val or not val.strip():
        return None
    try:
        return float(val.replace(",", "").strip())
    except ValueError:
        return None


def _parse_rows(csv_text: str) -> list[dict]:
    """
    Parse CSV rows into structured stock entries.
    Expected columns (0-indexed): B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, J=9, K=10, L=11
    """
    reader = csv.reader(io.StringIO(csv_text))
    entries = []

    for i, row in enumerate(reader):
        # Skip header rows (row 0 is metadata, row 1 is header)
        if i < 2:
            continue
        if len(row) < 8:
            continue

        ticker = row[1].strip()
        # Validate ticker: should be numeric (Taiwan stock codes)
        if not ticker or not re.match(r"^\d{4,6}$", ticker):
            continue

        name = row[2].strip() if len(row) > 2 else ""
        date_str = row[3].strip() if len(row) > 3 else ""
        status = row[4].strip() if len(row) > 4 else ""
        period = row[5].strip() if len(row) > 5 else ""
        strategy = row[6].strip() if len(row) > 6 else ""
        current_price = _parse_price(row[7]) if len(row) > 7 else None
        stop_loss = row[8].strip() if len(row) > 8 else ""
        # row[9] = 月成本 (mostly empty)
        position = row[10].strip() if len(row) > 10 else ""
        recent_action = row[11].strip() if len(row) > 11 else ""

        # Build merged note with labels
        note_parts = []
        if status:
            note_parts.append(f"狀態:{status}")
        if period:
            note_parts.append(f"週期:{period}")
        if strategy:
            note_parts.append(f"策略:{strategy}")
        if stop_loss:
            note_parts.append(f"停損:{stop_loss}")
        if position:
            note_parts.append(f"倉位:{position}")
        if recent_action:
            note_parts.append(f"動作:{recent_action}")

        note = " | ".join(note_parts) if note_parts else None

        entries.append({
            "ticker": ticker,
            "name": name,
            "date_str": date_str,
            "price": current_price,
            "note": note,
            "status": status,
        })

    return entries


def _sync_watchlist(
    chat_id: int,
    user_id: int,
    entries: list[dict],
    source_url: str,
    user_name: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """
    Sync parsed entries into WatchlistEntry.
    Returns (added, updated, removed) ticker lists.

    Logic:
    - Sheet 有的 ticker → 若已存在則用 sheet 資料覆蓋（不管原本是手動還是 gsheet 來的）
    - Sheet 有但 DB 沒有 → 新增，標記 source="gsheet"
    - DB 有且 source="gsheet" 但 sheet 已移除 → 刪除
    - DB 有且 source="manual"/None 但 sheet 已移除 → 不動（用戶手動加的保留）
    """
    added = []
    updated = []
    removed = []

    sheet_tickers = {e["ticker"] for e in entries}
    entries_map = {e["ticker"]: e for e in entries}

    with Session(engine) as session:
        # Get all existing entries for this user in this chat
        existing = session.exec(
            select(WatchlistEntry)
            .where(WatchlistEntry.chat_id == chat_id)
            .where(WatchlistEntry.user_id == user_id)
        ).all()

        existing_map = {e.ticker: e for e in existing}

        # Add or update
        for entry in entries:
            ticker = entry["ticker"]
            if ticker in existing_map:
                # 覆蓋：用 sheet 資料更新
                row = existing_map[ticker]
                changed = False
                if entry["note"] and row.note != entry["note"]:
                    row.note = entry["note"]
                    changed = True
                if entry["name"] and row.alias != entry["name"]:
                    row.alias = entry["name"]
                    changed = True
                if entry["price"] is not None and row.added_price != entry["price"]:
                    row.added_price = entry["price"]
                    changed = True
                # 標記為 gsheet 管理（即使原本是手動加的，現在 sheet 也有就歸 gsheet）
                if row.source != "gsheet":
                    row.source = "gsheet"
                    changed = True
                if user_name and row.user_name != user_name:
                    row.user_name = user_name
                    changed = True
                if changed:
                    session.add(row)
                    updated.append(entry)
            else:
                # New entry from sheet
                session.add(WatchlistEntry(
                    chat_id=chat_id,
                    user_id=user_id,
                    ticker=ticker,
                    alias=entry["name"] or None,
                    added_price=entry["price"],
                    note=entry["note"],
                    user_name=user_name,
                    source="gsheet",
                ))
                added.append(entry)

        # Remove: sheet 移除的就一起刪掉
        for ticker, row in existing_map.items():
            if ticker not in sheet_tickers:
                session.delete(row)
                removed.append(ticker)

        session.commit()

    return added, updated, removed


def _format_entry_line(entry: dict) -> str:
    """Format a single entry dict into a display line."""
    ticker = entry["ticker"]
    name = entry.get("name") or ""
    price = entry.get("price")
    note = entry.get("note") or ""
    price_str = f" ${price:,.1f}" if price else ""
    name_str = f" {name}" if name else ""
    line = f"  {ticker}{name_str}{price_str}"
    if note:
        line += f"\n    📝 {note}"
    return line


async def gsheet_sync_job() -> None:
    """
    Scheduled job: check all registered Google Sheets for updates,
    sync watchlist, and notify users of changes.
    """
    from ..models.subscriber import Subscriber
    from ..utils.pii import redact_telegram_id

    settings = get_settings()
    pii_salt = settings.LOG_PII_SALT or None

    # Load all subscriptions
    def _load_subs():
        with Session(engine) as session:
            return session.exec(select(GSheetSubscription)).all()

    subs = await asyncio.to_thread(_load_subs)
    if not subs:
        return

    # Get bot instance
    from .. import main as _main_mod
    from telegram import Bot

    if getattr(_main_mod, "bot_app", None) and _main_mod.bot_app.bot:
        bot = _main_mod.bot_app.bot
    else:
        bot = Bot(token=settings.TELEGRAM_TOKEN)

    for sub in subs:
        try:
            sheet_id, gid = _parse_sheet_url(sub.url)
        except ValueError as e:
            logger.warning("Invalid gsheet URL for sub %d: %s", sub.id, e)
            continue

        csv_text = await fetch_sheet_csv(sheet_id, gid)
        if csv_text is None:
            continue

        current_hash = _hash_content(csv_text)

        # Skip if no change
        if sub.last_hash and current_hash == sub.last_hash:
            continue

        # Parse and sync
        entries = _parse_rows(csv_text)
        if not entries:
            logger.info("GSheet sync: no valid entries in %s", sub.url)
            continue

        added, updated, removed = await asyncio.to_thread(
            _sync_watchlist, sub.chat_id, sub.user_id, entries, sub.url,
            user_name=sub.user_name,
        )

        # Update subscription record
        def _update_sub():
            with Session(engine) as session:
                row = session.get(GSheetSubscription, sub.id)
                if row:
                    row.last_hash = current_hash
                    row.synced_at = datetime.now()
                    session.add(row)
                    session.commit()

        await asyncio.to_thread(_update_sub)

        # Notify if there were changes
        if not added and not updated and not removed:
            continue

        lines = ["📊 *試算表自選股已同步*"]
        if sub.label:
            lines[0] += f"（{sub.label}）"
        if added:
            lines.append(f"\n➕ *新增 {len(added)} 檔：*")
            for e in added:
                lines.append(_format_entry_line(e))
        if updated:
            lines.append(f"\n✏️ *更新 {len(updated)} 檔：*")
            for e in updated:
                lines.append(_format_entry_line(e))
        if removed:
            lines.append(f"\n🗑 移除：{', '.join(removed)}")
        lines.append(f"\n共 {len(entries)} 檔持股")

        message = "\n".join(lines)

        # Notify wlist_enabled subscribers
        def _get_wlist_subs():
            with Session(engine) as session:
                from ..models.subscriber import Subscriber
                subs = session.exec(
                    select(Subscriber).where(Subscriber.wlist_enabled == True)
                ).all()
                return [(s.chat_id, s.topic_id) for s in subs]

        targets = await asyncio.to_thread(_get_wlist_subs)

        for cid, tid in targets:
            try:
                kwargs: dict = {
                    "chat_id": cid,
                    "text": message,
                    "parse_mode": "Markdown",
                }
                if tid:
                    kwargs["message_thread_id"] = tid
                await bot.send_message(**kwargs)
            except Exception as e:
                logger.error(
                    "GSheet sync notify failed to %s: %s",
                    redact_telegram_id(cid, salt=pii_salt),
                    e,
                )
            await asyncio.sleep(0.3)

    logger.info("GSheet sync job completed: checked %d subscriptions", len(subs))



async def gsheet_sync_for_user(chat_id: int, user_id: int) -> str:
    """
    手動同步指定用戶的所有已註冊試算表。
    回傳結果訊息字串。
    """
    from ..models.gsheet_sub import GSheetSubscription

    def _load_subs():
        with Session(engine) as session:
            return session.exec(
                select(GSheetSubscription)
                .where(GSheetSubscription.chat_id == chat_id)
                .where(GSheetSubscription.user_id == user_id)
            ).all()

    subs = await asyncio.to_thread(_load_subs)
    if not subs:
        return "❌ 你還沒有註冊任何試算表。\n用 /gsheet add <URL> 來新增。"

    all_added = []
    all_updated = []
    all_removed = []
    errors = []

    for sub in subs:
        try:
            sheet_id, gid = _parse_sheet_url(sub.url)
        except ValueError:
            errors.append(f"URL 格式錯誤：{sub.url[:30]}...")
            continue

        csv_text = await fetch_sheet_csv(sheet_id, gid)
        if csv_text is None:
            errors.append(f"抓取失敗（試算表可能不是公開的）")
            continue

        current_hash = _hash_content(csv_text)
        entries = _parse_rows(csv_text)

        if not entries:
            errors.append(f"無法解析有效股票資料")
            continue

        added, updated, removed = await asyncio.to_thread(
            _sync_watchlist, chat_id, user_id, entries, sub.url,
            user_name=sub.user_name,
        )

        all_added.extend(added)
        all_updated.extend(updated)
        all_removed.extend(removed)

        # Update hash and synced_at
        def _update(sub_id=sub.id, h=current_hash):
            with Session(engine) as session:
                row = session.get(GSheetSubscription, sub_id)
                if row:
                    row.last_hash = h
                    row.synced_at = datetime.now()
                    session.add(row)
                    session.commit()

        await asyncio.to_thread(_update)

    # Build result message
    lines = ["✅ 同步完成"]
    if all_added:
        lines.append(f"\n➕ *新增 {len(all_added)} 檔：*")
        for e in all_added:
            lines.append(_format_entry_line(e))
    if all_updated:
        lines.append(f"\n✏️ *更新 {len(all_updated)} 檔：*")
        for e in all_updated:
            lines.append(_format_entry_line(e))
    if all_removed:
        lines.append(f"\n🗑 移除：{', '.join(all_removed)}")
    if not all_added and not all_updated and not all_removed:
        lines.append("無變更")
    if errors:
        lines.append(f"\n⚠️ 錯誤：{'; '.join(errors)}")

    return "\n".join(lines)
