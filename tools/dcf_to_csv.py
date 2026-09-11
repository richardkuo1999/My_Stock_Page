"""dcf_to_csv — 把 DCF 估值結果輸出成 CSV（單檔或多檔皆可）。

用法:
    python tools/dcf_to_csv.py 2330
    python tools/dcf_to_csv.py 2330 2454 2317 --out dcf.csv
    python tools/dcf_to_csv.py 2330,2454,2317            # 逗號分隔也可
    python tools/dcf_to_csv.py 2330 2454 --concurrency 4

行為:
    - 對每個代號呼叫 uanalyze.fetch_dcf_valuation（純計算，不呼叫 AI），
      多檔時以 asyncio 並行（預設同時 4 個），單檔失敗不影響其他檔。
    - 有 --out 就寫檔，否則印到 stdout（可自行 > 導向檔案）。
    - 成功的股票填完整欄位；失敗的股票只填代號 + error 欄，其餘留空，
      這樣一張表就能看出哪些查得到、哪些查不到。

不動 uanalyze.py：CSV 是不同輸出格式，拆成獨立小工具，維持 uanalyze
每個 CLI 分支「輸出 JSON」的一致慣例。
"""

import argparse
import asyncio
import csv
import io
import sys

# 支援兩種執行方式：`python tools/dcf_to_csv.py`（同層 import）
# 以及 `python -m tools.dcf_to_csv`（package import）。
try:
    from uanalyze import DEFAULT_MULTI_CONCURRENCY, fetch_dcf_valuation
except ImportError:  # pragma: no cover - 依執行方式擇一
    from tools.uanalyze import DEFAULT_MULTI_CONCURRENCY, fetch_dcf_valuation

# CSV 欄位順序：代號在前，其餘沿用 fetch_dcf_valuation 回傳 dict 的鍵，
# 最後補一個 error 欄給查不到資料的股票。
CSV_FIELDS = [
    "symbol",
    "每股合理內在價值",
    "1年後前瞻合理價值",
    "當前時間加權基期",
    "營收動能",
    "2025實際獲利",
    "2026E",
    "最遠預估年份及獲利",
    "信心度",
    "error",
]


def _parse_symbols(raw_args: list[str]) -> list[str]:
    """把命令列的代號參數展開成清單（支援空白與逗號混用），去重保序。"""
    symbols: list[str] = []
    seen: set[str] = set()
    for chunk in raw_args:
        for part in chunk.split(","):
            s = part.strip().upper()
            if s and s not in seen:
                seen.add(s)
                symbols.append(s)
    return symbols


async def _run_one(symbol: str, sem: asyncio.Semaphore) -> dict:
    """跑單檔 DCF，永遠回一個「已對齊 CSV 欄位」的 row dict（含失敗情形）。"""
    async with sem:
        try:
            result = await fetch_dcf_valuation(symbol)
        except Exception as e:  # noqa: BLE001 - 單顆失敗隔離，不拖垮整批
            result = {"error": f"{symbol} DCF 計算失敗：{e}"}

    row = {k: "" for k in CSV_FIELDS}
    row["symbol"] = symbol
    if "error" in result:
        row["error"] = result["error"]
    else:
        for k, v in result.items():
            if k in row:
                row[k] = v
    return row


async def collect_rows(symbols: list[str], concurrency: int) -> list[dict]:
    """並行跑所有代號，回傳與輸入順序一致的 row 清單。"""
    sem = asyncio.Semaphore(max(1, concurrency))
    tasks = [_run_one(s, sem) for s in symbols]
    return await asyncio.gather(*tasks)


def rows_to_csv(rows: list[dict]) -> str:
    """把 row 清單序列化成 CSV 字串（含表頭）。"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 DCF 估值結果輸出成 CSV（單檔或多檔皆可）。"
    )
    parser.add_argument(
        "symbols",
        nargs="+",
        help="股票代號，可空白或逗號分隔，例如 2330 2454 或 2330,2454",
    )
    parser.add_argument(
        "--out",
        help="輸出 CSV 檔路徑；未指定則印到 stdout。",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_MULTI_CONCURRENCY,
        help=f"多檔時同時並行的數量上限（預設 {DEFAULT_MULTI_CONCURRENCY}）。",
    )
    args = parser.parse_args(argv)

    symbols = _parse_symbols(args.symbols)
    if not symbols:
        print("錯誤：請提供至少一個股票代號", file=sys.stderr)
        return 1

    rows = asyncio.run(collect_rows(symbols, args.concurrency))
    csv_text = rows_to_csv(rows)

    if args.out:
        # utf-8-sig：加 BOM，Excel 開中文欄位才不會亂碼。
        with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
            f.write(csv_text)
        ok = sum(1 for r in rows if not r["error"])
        failed = len(rows) - ok
        print(f"已寫入 {args.out}：成功 {ok} 檔，失敗 {failed} 檔", file=sys.stderr)
    else:
        sys.stdout.write(csv_text)

    # 只要有任一檔成功就回 0；全部失敗才回 1。
    return 0 if any(not r["error"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
