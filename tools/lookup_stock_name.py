"""lookup_stock_name — 台股代號 ↔ 公司名稱 對照表（純資料工具）

這是一個「純資料」工具：只負責讀 / 寫本地 JSON 對照表，**本身不呼叫任何 AI**。

主資料來源是 UAnalyze 官方 gidp `StockPool`（全台股 ~12,361 檔 `{stock_code, stock_name}`），
由 `refresh_pool()` 拉取後灌進本地表；`--set` 手動寫回退化為「後援」，只在 StockPool
未涵蓋或需要覆寫時使用（且手動項不會被刷新碾掉）。

「查出未知代號的公司名稱」若 StockPool 仍未命中，才回退給 Agent 判斷後 `--set` 寫回。

管線設計：chat_bot → AI → tool → AI → tool（AI 協調，工具保持純粹確定性）。

用法:
    python tools/lookup_stock_name.py 2330
        → 查代號。命中回 {"symbol": "2330", "name": "台積電", "found": true}
          未命中回 {"symbol": "9999", "name": null, "found": false}
          （此時 Agent 可自行判斷公司名稱，再用 --set 寫回當後援）

    python tools/lookup_stock_name.py --set 9999 某公司
        → 寫入對照表（手動後援），回 {"symbol": "9999", "name": "某公司", "saved": true}

    python tools/lookup_stock_name.py --refresh
        → 從 UAnalyze StockPool 全表刷新本地對照表（首次部署 / 定期執行），
          回 {"refreshed": 筆數}

回傳: 一律為單行 JSON。
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NAMES_FILE = _DATA_DIR / "stock_names.json"
META_FILE = _DATA_DIR / "stock_names_meta.json"

# 刷新週期：超過此秒數（7 天）視為過期，refresh_pool() 會重新拉 StockPool。
REFRESH_TTL_SEC = 7 * 24 * 3600

# Seed：最後後援（連 StockPool 都拿不到時，至少有這些大型股可用）。
SEED: dict[str, str] = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2308": "台達電",
    "2303": "聯電",
    "2412": "中華電",
    "2881": "富邦金",
    "2882": "國泰金",
    "2891": "中信金",
    "3711": "日月光投控",
    "1301": "台塑",
    "1303": "南亞",
    "2002": "中鋼",
    "3008": "大立光",
    "2379": "瑞昱",
    "3034": "聯詠",
    "2357": "華碩",
    "2382": "廣達",
    "3231": "緯創",
}


def load_names() -> dict[str, str]:
    """Load the code→name map, bootstrapping from SEED on first use.

    純同步、只讀本地檔，**不發任何網路請求**（避免阻塞呼叫端，例如 fetch_news 個股過濾）。
    """
    try:
        if NAMES_FILE.exists():
            data = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s", NAMES_FILE, e)
    save_names(dict(SEED))
    return dict(SEED)


def save_names(mapping: dict[str, str]) -> None:
    """Persist the code→name map to disk."""
    try:
        NAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        NAMES_FILE.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Failed to write %s: %s", NAMES_FILE, e)


def get_name(symbol: str) -> str | None:
    """Return the cached company name for a code, or None.

    同步介面（fetch_news 依賴），不發網路請求。
    """
    return load_names().get(symbol)


def set_name(symbol: str, name: str) -> None:
    """Store a code→name entry (手動後援), so future lookups hit the cache."""
    names = load_names()
    names[symbol] = name
    save_names(names)


def _load_meta() -> dict:
    try:
        if META_FILE.exists():
            data = json.loads(META_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s", META_FILE, e)
    return {}


def _save_meta(meta: dict) -> None:
    try:
        META_FILE.parent.mkdir(parents=True, exist_ok=True)
        META_FILE.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Failed to write %s: %s", META_FILE, e)


def _is_stale() -> bool:
    """Return True if the local pool is missing or older than REFRESH_TTL_SEC."""
    if not NAMES_FILE.exists():
        return True
    meta = _load_meta()
    refreshed_at = meta.get("refreshed_at")
    if not isinstance(refreshed_at, (int, float)):
        return True
    return (time.time() - refreshed_at) > REFRESH_TTL_SEC


async def fetch_stock_pool() -> dict[str, str]:
    """Fetch the full Taiwan stock code→name map from UAnalyze gidp StockPool.

    純資料拉取，不呼叫 AI。用 async httpx（不用 requests）。失敗回 {}。
    局部 import tools.uanalyze 以避免頂層 import 循環 / 副作用。
    """
    try:
        import httpx

        # 局部 import：避免 lookup_stock_name 頂層依賴 uanalyze（防循環 / 副作用）。
        # 支援兩種執行情境：套件 import（tools.uanalyze）與直接跑 script（uanalyze）。
        try:
            from tools.uanalyze import _auth, GIDP_BASE_URL, DEFAULT_TIMEOUT
        except ImportError:
            from uanalyze import _auth, GIDP_BASE_URL, DEFAULT_TIMEOUT

        headers = _auth.gidp_headers()
        url = f"{GIDP_BASE_URL}/data_fetch/api/StockPool"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params={"country": "TW"})
        if r.status_code != 200:
            logger.warning("StockPool fetch failed: HTTP %d", r.status_code)
            return {}
        data = r.json().get("data")
        # data 為 flat list；防禦性地容忍 {"data": [...]} 包一層的情況。
        if isinstance(data, dict):
            data = data.get("data")
        if not isinstance(data, list):
            logger.warning("StockPool response has unexpected shape")
            return {}
        pool: dict[str, str] = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            code = row.get("stock_code")
            name = row.get("stock_name")
            if code and name:
                pool[str(code)] = str(name)
        return pool
    except Exception as e:
        logger.warning("fetch_stock_pool error: %s", e)
        return {}


async def refresh_pool(force: bool = False) -> int:
    """Refresh the local map from StockPool（主資料）；手動 --set 項不被碾掉。

    - 非 force 時，僅在本地表缺失或過期（>7 天）才刷新。
    - pool 為主：先鋪 pool，再用「現有表中 pool 未涵蓋的鍵」覆蓋回去，
      這樣使用者 --set 的獨有代號會保留，而 pool 有的代號以官方名為準。
    - pool 空（拉取失敗）時**不覆蓋**現有表，降級回既有資料，回 0。

    回傳寫入的總筆數（合併後表的大小）。
    """
    if not force and not _is_stale():
        return 0

    pool = await fetch_stock_pool()
    if not pool:
        # 降級：拉不到就不動現有表。
        logger.warning("refresh_pool: empty pool, keeping existing table")
        return 0

    existing = load_names()
    merged = dict(pool)
    # 保留現有表中 pool 未涵蓋的鍵（使用者手動 --set 的後援項）。
    for code, name in existing.items():
        if code not in merged:
            merged[code] = name

    save_names(merged)
    _save_meta({"refreshed_at": time.time(), "count": len(merged)})
    return len(merged)


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--refresh":
        count = asyncio.run(refresh_pool(force=True))
        print(json.dumps({"refreshed": count}, ensure_ascii=False))
    elif args and args[0] == "--set":
        if len(args) < 3:
            print(json.dumps({"error": "usage: --set <symbol> <name>"}, ensure_ascii=False))
            sys.exit(1)
        symbol, name = args[1], args[2]
        set_name(symbol, name)
        print(json.dumps({"symbol": symbol, "name": name, "saved": True}, ensure_ascii=False))
    elif args:
        symbol = args[0]
        name = get_name(symbol)
        print(
            json.dumps(
                {"symbol": symbol, "name": name, "found": name is not None},
                ensure_ascii=False,
            )
        )
    else:
        print(
            json.dumps(
                {"error": "usage: lookup_stock_name.py <symbol> | --set <symbol> <name> | --refresh"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)
