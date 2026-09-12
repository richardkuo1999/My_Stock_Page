"""analysis.reports — UAnalyze 研究報告清單整理（call raw/uanalyze）。

主要消費者：bot/scheduler.py 的 UAnalyze 報告推播 job（非 Agent 路徑）。
把 raw report-summaries 的原始 items 整理成 {reports: [{id, stock_code, stock_name,
title, date, summary}]}，供推播去重（用 id）與顯示。
"""

import asyncio
import json
import sys

try:
    from tools.raw import uanalyze as raw_uanalyze
except ImportError:  # pragma: no cover - CLI standalone fallback
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    from tools.raw import uanalyze as raw_uanalyze


async def list_latest_reports(limit: int = 50) -> dict:
    """全站最新研究報告清單（推播監控用）。call raw fetch_raw_report_summaries() 再整理。"""
    raw = await raw_uanalyze.fetch_raw_report_summaries(limit=limit, offset=0)
    if not isinstance(raw, dict) or "error" in raw:
        return {"error": (raw or {}).get("error", "UAnalyze 無法取得最新報告列表")}
    if "data" not in raw:
        return {"error": "UAnalyze 無法取得最新報告列表"}

    # data 可能是 [...] 或 {data:[...]}。
    inner = raw["data"]
    items = inner.get("data", []) if isinstance(inner, dict) else inner

    reports = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        reports.append({
            "id": item.get("id"),
            "stock_code": item.get("name", ""),          # UAnalyze schema: name=股票代號
            "stock_name": item.get("stock_name", ""),
            "title": item.get("question_type", "") or item.get("title", ""),
            "date": (item.get("content_date", "") or item.get("date", ""))[:10],
            "summary": item.get("summary", ""),
        })
    return {"reports": reports}


async def get_reports(symbol: str) -> dict:
    """某股的研究報告清單（Agent 用）。call raw fetch_raw_report_summaries(symbol)。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    raw = await raw_uanalyze.fetch_raw_report_summaries(symbol)
    if not isinstance(raw, dict) or "error" in raw:
        return {"error": (raw or {}).get("error", f"查無 {symbol} 的研究報告")}
    inner = raw.get("data")
    items = inner.get("data", []) if isinstance(inner, dict) else inner
    reports = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        reports.append({
            "id": item.get("id"),
            "title": item.get("question_type", "") or item.get("title", ""),
            "date": (item.get("content_date", "") or item.get("date", ""))[:10],
            "summary": item.get("summary", ""),
        })
    return {"symbol": symbol, "reports": reports}


if __name__ == "__main__":
    args = sys.argv[1:]
    # 帶代號 → 單股；不帶 → 全站最新
    if args and not args[0].startswith("--"):
        result = asyncio.run(get_reports(args[0]))
    else:
        result = asyncio.run(list_latest_reports())
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(1 if isinstance(result, dict) and "error" in result else 0)
