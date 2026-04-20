"""
Blake Finance CHIPS 資料抓取服務。

- 00981A: 持股變化（張數變化不為 0）
- 00981A_match_888: 大額權證買超持股
日期可透過 date 參數指定，格式 YYYY-MM-DD。
"""

import logging
import re
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from .http import create_session

logger = logging.getLogger(__name__)

from ..config import get_settings

DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def fetch_chips_data(
    date_str: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> str:
    """
    抓取指定日期的 CHIPS 資料頁面，回傳整理後的文字。

    Args:
        date_str: 日期，格式 YYYY-MM-DD。若為 None 則使用今天。
        session: 可選的 aiohttp session，若未提供會建立臨時 session。

    Returns:
        整理後的文字內容，適合直接傳給 Telegram。
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    url = f"{get_settings().BLAKE_CHIPS_URL_981}?date={date_str}"
    own_session = session is None

    if own_session:
        timeout = aiohttp.ClientTimeout(total=60)
        session = create_session(headers=DEFAULT_HEADERS, timeout=timeout)

    try:
        logger.info("Fetching CHIPS 981: %s", url)
        async with session.get(url, ssl=True) as resp:
            if resp.status != 200:
                return f"❌ 無法取得資料 (HTTP {resp.status})"

            text = await resp.text()
            return _parse_page(text, date_str)
    except aiohttp.ClientError as e:
        logger.exception("Blake CHIPS fetch failed")
        return f"❌ 連線失敗：{e}"
    finally:
        if own_session and session and not session.closed:
            await session.close()


def _parse_page_888(html: str, date_str: str) -> str:
    """解析 00981A_match_888 頁面。與 hold981 相同格式：代號 名稱 張數張 (金額萬)，依權證買超金額排序。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    tables = soup.find_all("table")
    lines = [f"📅 00981A & 大額權證買超 ({date_str})\n"]
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
        if not header_cells:
            continue
        # 找欄位：股票代號、股票名稱、持有張數、持有比例、權證買超金額
        idx_code = _find_column_index(header_cells, ("股票代號", "代號", "代碼"))
        idx_name = _find_column_index(header_cells, ("股票名稱", "名稱"))
        idx_shares = _find_column_index(header_cells, ("持有張數", "張數"))
        idx_pct = _find_column_index(header_cells, ("持有比例", "比例", "權重"))
        idx_amount = _find_column_index(header_cells, ("權證買超金額", "買超金額", "金額"))
        if idx_code is None or idx_name is None:
            continue
        kept = []
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            code = cells[idx_code] if idx_code < len(cells) else ""
            name = cells[idx_name] if idx_name < len(cells) else ""
            shares = cells[idx_shares] if idx_shares is not None and idx_shares < len(cells) else ""
            pct = cells[idx_pct] if idx_pct is not None and idx_pct < len(cells) else ""
            amount = cells[idx_amount] if idx_amount is not None and idx_amount < len(cells) else ""
            amount_num = 0.0
            try:
                amount_num = float(amount.replace(",", ""))
            except (ValueError, AttributeError):
                pass
            pct_str = f"{pct}%" if pct and not str(pct).endswith("%") else (pct or "")
            line = f"📊 {code} {name}  {shares}張 {pct_str} ({amount}萬)".strip()
            kept.append((amount_num, line))
        if kept:
            kept.sort(key=lambda x: x[0], reverse=True)  # 依權證買超金額由大到小
            lines.extend(line for _, line in kept)
    if len(lines) <= 1:
        lines.append("（無資料）")
    result = "\n".join(lines)
    if len(result) > 4000:
        result = result[:3997] + "\n..."
    return result or "（無資料）"


async def fetch_chips_data_888(
    date_str: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> str:
    """
    抓取 00981A_match_888 CHIPS 持股資料。
    該頁為持股列表，無張數變化欄。
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    url = f"{get_settings().BLAKE_CHIPS_URL_888}?date={date_str}"
    own_session = session is None
    if own_session:
        timeout = aiohttp.ClientTimeout(total=60)
        session = create_session(headers=DEFAULT_HEADERS, timeout=timeout)
    try:
        logger.info("Fetching CHIPS 888: %s", url)
        async with session.get(url, ssl=True) as resp:
            if resp.status != 200:
                return f"❌ 無法取得資料 (HTTP {resp.status})"
            text = await resp.text()
            return _parse_page_888(text, date_str)
    except aiohttp.ClientError as e:
        logger.exception("Blake CHIPS 888 fetch failed")
        return f"❌ 連線失敗：{e}"
    finally:
        if own_session and session and not session.closed:
            await session.close()


# 張數變化欄位的表頭關鍵字（不含「張數」以免誤匹配到絕對張數欄）
CHANGE_COLUMN_KEYWORDS = ("張數變化", "張數變動", "增減", "增减", "變化", "變動", "異動")


def _find_column_index(
    header_cells: list[str], keywords: tuple[str, ...], exclude: tuple[str, ...] = ()
) -> int | None:
    """找出表頭中符合關鍵字的欄位索引。"""
    for i, cell in enumerate(header_cells):
        if any(ex in cell for ex in exclude):
            continue
        if any(kw in cell for kw in keywords):
            return i
    return None


def _find_output_column_indices(header_cells: list[str]) -> list[int]:
    """找出 代號、名稱、張數、張數變化、買超金額 的欄位索引。"""
    indices = []
    # 代號
    indices.append(_find_column_index(header_cells, ("代號", "代碼")))
    # 名稱
    indices.append(_find_column_index(header_cells, ("名稱", "股票")))
    # 張數（排除張數變化）
    indices.append(_find_column_index(header_cells, ("張數",), exclude=("變化", "變動")))
    # 張數變化
    indices.append(_find_column_index(header_cells, CHANGE_COLUMN_KEYWORDS))
    # 買超金額
    indices.append(_find_column_index(header_cells, ("買超金額", "買超", "金額")))
    return indices


def _parse_change_numeric(val: str) -> float:
    """將張數變化字串轉為數值，用於排序。"""
    val = val.strip().replace(",", "").replace(" ", "").replace("（", "(").replace("）", ")")
    m = re.match(r"^([+\-])?\(?([\d.]+)\)?%?$", val)
    if m:
        sign_str, num = m.group(1), float(m.group(2))
        if sign_str == "-" or (sign_str is None and "(" in val):
            return -num
        return num
    return 0.0


def _get_change_sign(val: str) -> int:
    """回傳 1=增、-1=減、0=零。"""
    val = val.strip().replace(",", "").replace(" ", "").replace("（", "(").replace("）", ")")
    if not val or val in ("-", "—", "－", "0", "0.0"):
        return 0
    m = re.match(r"^([+\-])?\(?([\d.]+)\)?%?$", val)
    if m:
        sign_str, num = m.group(1), float(m.group(2))
        if num == 0:
            return 0
        if sign_str == "-" or (sign_str is None and "(" in val):
            return -1
        return 1
    return 0


def _is_nonzero_change(val: str) -> bool:
    """判斷該欄位是否為非零的張數變化。"""
    val = val.strip().replace(",", "").replace(" ", "").replace("（", "(").replace("）", ")")
    if not val or val in ("-", "—", "－", "0", "0.0"):
        return False
    # +123、-45、(123)、+1,234
    m = re.match(r"^[+\-]?\(?([\d.]+)\)?%?$", val)
    if m:
        try:
            return float(m.group(1)) != 0
        except ValueError:
            return False
    return False


def _parse_page(html: str, date_str: str, title: str = "00981A持股變化") -> str:
    """解析 HTML 頁面，只擷取張數有變化的列。"""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style"]):
        tag.decompose()

    tables = soup.find_all("table")
    lines = [f"📅 {title} ({date_str})\n"]

    if tables:
        for i, table in enumerate(tables):
            rows = table.find_all("tr")
            if not rows:
                continue
            # 表頭
            header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["td", "th"])]
            if not header_cells:
                continue
            indices = _find_output_column_indices(header_cells)
            idx_change = indices[3]  # 張數變化
            if idx_change is None:
                continue
            kept = []  # (change_numeric, formatted_line)

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                cell_texts = [c.get_text(strip=True) for c in cells]
                if idx_change >= len(cell_texts) or not _is_nonzero_change(cell_texts[idx_change]):
                    continue
                change_val = cell_texts[idx_change]
                change_num = _parse_change_numeric(change_val)
                # Emoji 區分增減：📈 增、📉 減
                sign = _get_change_sign(change_val)
                emoji = "📈" if sign > 0 else "📉"
                code = (
                    cell_texts[indices[0]]
                    if indices[0] is not None and indices[0] < len(cell_texts)
                    else ""
                )
                name = (
                    cell_texts[indices[1]]
                    if indices[1] is not None and indices[1] < len(cell_texts)
                    else ""
                )
                shares = (
                    cell_texts[indices[2]]
                    if indices[2] is not None and indices[2] < len(cell_texts)
                    else ""
                )
                amount = (
                    cell_texts[indices[4]]
                    if indices[4] is not None and indices[4] < len(cell_texts)
                    else ""
                )
                change_display = change_val if change_val.startswith("-") else f"+{change_val}"
                amount_str = f"({amount}萬)" if amount else ""
                line = f"{emoji} {code} {name}  {shares}張 {change_display} {amount_str}".strip()
                kept.append((change_num, line))
            if kept:
                # 增的由大到小、減的由大到小（-236 在 -73 前）
                kept.sort(key=lambda x: (0 if x[0] >= 0 else 1, -x[0] if x[0] >= 0 else x[0]))
                lines.extend(line for _, line in kept)
            if tables and i < len(tables) - 1 and kept:
                lines.append("")
    else:
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            main.get_text(separator="\n", strip=True)
            lines.append("（無表格結構，請檢查頁面）")
        else:
            lines.append("（無法解析頁面結構）")

    if len(lines) <= 1:
        lines.append("（當日無持股變化）")

    result = "\n".join(lines)
    # Telegram 單則訊息上限約 4096 字元
    if len(result) > 4000:
        result = result[:3997] + "\n..."
    return result or "（無資料）"
