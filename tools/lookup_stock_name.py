"""lookup_stock_name — 台股代號 ↔ 公司名稱 對照表（純資料工具）

這是一個「純資料」工具：只負責讀 / 寫本地 JSON 對照表，**本身不呼叫任何 AI**。
「查出未知代號的公司名稱」這件智能工作屬於 Agent；Agent 查到後再用本工具
`--set` 把答案寫回對照表，讓對照表隨使用自我成長。

管線設計：chat_bot → AI → tool → AI → tool（AI 協調，工具保持純粹確定性）。

用法:
    python tools/lookup_stock_name.py 2330
        → 查代號。命中回 {"symbol": "2330", "name": "台積電", "found": true}
          未命中回 {"symbol": "9999", "name": null, "found": false}
          （此時 Agent 應自行判斷公司名稱，再用 --set 寫回）

    python tools/lookup_stock_name.py --set 9999 某公司
        → 寫入對照表，回 {"symbol": "9999", "name": "某公司", "saved": true}

回傳: 一律為單行 JSON。
"""

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

NAMES_FILE = Path(__file__).resolve().parent.parent / "data" / "stock_names.json"

# Seed used to bootstrap the file on first run (common Taiwan large-caps).
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
    """Load the code→name map, bootstrapping from SEED on first use."""
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
    """Return the cached company name for a code, or None."""
    return load_names().get(symbol)


def set_name(symbol: str, name: str) -> None:
    """Store a code→name entry, so future lookups hit the cache."""
    names = load_names()
    names[symbol] = name
    save_names(names)


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "--set":
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
        print(json.dumps({"error": "usage: lookup_stock_name.py <symbol> | --set <symbol> <name>"}, ensure_ascii=False))
        sys.exit(1)
