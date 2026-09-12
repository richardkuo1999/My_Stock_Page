"""analysis.forecast — 法人前瞻預估整理（call raw/uanalyze，做整理/挑值）。

- smart_estimate: 把 raw 的 8 指標各 3 欄（平均/最低/最高）整理成逐年 series。
- forecast_route: 未來五季路徑 + 評等佔比趨勢整理。

純整理（無外部 AI）；取數在 raw 層（含登入）。
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


def _clean_num(v: object) -> float | None:
    """空字串（未來太遠年份）轉 None；數字原樣。"""
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _latest(data_map: dict, n: int) -> list[tuple[str, object]]:
    if not isinstance(data_map, dict) or not data_map:
        return []
    return sorted(data_map.items(), key=lambda kv: kv[0])[-n:]


async def smart_estimate(symbol: str, recent: int = 5) -> dict:
    """法人前瞻預估（平均/最低/最高，逐年）。call raw fetch_raw_smart_estimate 再整理。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    raw = await raw_uanalyze.fetch_raw_smart_estimate(symbol)
    if isinstance(raw, dict) and "error" in raw:
        return raw

    estimates: dict = {}
    for label, rows in raw.items():
        if not isinstance(rows, dict):
            continue
        avg = low = high = {}
        for row in rows.values():
            if not isinstance(row, dict):
                continue
            nm = row.get("ChineseAccount", "")
            dm = row.get("Data", {})
            if "平均" in nm:
                avg = dm
            elif "最低" in nm:
                low = dm
            elif "最高" in nm:
                high = dm
        years = sorted(set(avg) | set(low) | set(high))[-recent:]
        series = [
            {"year": y, "平均": _clean_num(avg.get(y)), "最低": _clean_num(low.get(y)),
             "最高": _clean_num(high.get(y))}
            for y in years
        ]
        if series:
            estimates[label] = series

    if not estimates:
        return {"error": f"查無 {symbol} 的法人前瞻預估資料"}
    return {
        "symbol": symbol,
        "unit_note": "營收/EBIT/EBITDA/淨利為千元；EPS/每股股息為元；毛利率為 %；(f) 為預估年度",
        "estimates": estimates,
    }


async def forecast_route(symbol: str, recent: int = 6) -> dict:
    """未來五季 營收/EPS/毛利率/營益率 預估路徑 + 分析師評等佔比趨勢。call raw 再整理。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    eps_raw, margin_raw, rating_raw = await asyncio.gather(
        raw_uanalyze.fetch_raw_eps_route(symbol),
        raw_uanalyze.fetch_raw_margin_route(symbol),
        raw_uanalyze.fetch_raw_rating_trend(symbol),
    )

    route: dict = {}

    def _add(raw: dict) -> None:
        if not isinstance(raw, dict) or "error" in raw:
            return
        for row in raw.values():
            if not isinstance(row, dict):
                continue
            nm = row.get("ChineseAccount", "")
            dm = row.get("Data", {})
            if nm and dm:
                route[nm] = [{"period": p, "value": _clean_num(v)} for p, v in _latest(dm, 5)]

    _add(eps_raw)
    _add(margin_raw)

    rating_trend: list[dict] = []
    if isinstance(rating_raw, dict) and "error" not in rating_raw:
        opt = mid = pess = price = {}
        for row in rating_raw.values():
            if not isinstance(row, dict):
                continue
            nm = row.get("ChineseAccount", "")
            dm = row.get("Data", {})
            if "樂觀" in nm:
                opt = dm
            elif "中立" in nm:
                mid = dm
            elif "悲觀" in nm:
                pess = dm
            elif "收盤價" in nm:
                price = dm
        months = sorted(set(opt) | set(mid) | set(pess))[-recent:]
        rating_trend = [
            {"month": m, "樂觀": _clean_num(opt.get(m)), "中立": _clean_num(mid.get(m)),
             "悲觀": _clean_num(pess.get(m)), "收盤價": _clean_num(price.get(m))}
            for m in months
        ]

    if not route and not rating_trend:
        return {"error": f"查無 {symbol} 的預估路徑/評等資料"}
    out: dict = {"symbol": symbol}
    if route:
        out["route"] = route
    if rating_trend:
        out["rating_trend"] = rating_trend
    return out


_MODES = {"smart-estimate": smart_estimate, "forecast-route": forecast_route}


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = None
    symbol = None
    for flag in _MODES:
        if f"--{flag}" in args:
            mode = flag
            idx = args.index(f"--{flag}")
            if idx + 1 < len(args):
                symbol = args[idx + 1]
            break
    if not mode or not symbol:
        print(json.dumps(
            {"error": "用法: python tools/analysis/forecast.py [--smart-estimate|--forecast-route] <代號>"},
            ensure_ascii=False,
        ))
        sys.exit(1)
    result = asyncio.run(_MODES[mode](symbol))
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(1 if isinstance(result, dict) and "error" in result else 0)
