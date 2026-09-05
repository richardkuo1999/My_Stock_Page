"""valuation — 估值計算（CLI + import 雙入口）

本工具不直接打 API，而是 import 各 raw-data 工具（cnyes/finmind/fugle/yfinance_data）
拿原始資料，套用估值公式。數學核心（線性回歸均值回歸、標準差帶、四分位、百分位）
搬自舊版 analysis_bot/services/math_utils.py，純 numpy。

估值方式:
  --lohas 2330 [--years 3.5]   樂活五線譜（股價線性回歸 ±3SD 七線 + 機率）
  --pe 2330                    PE 河流圖（歷史本益比四分位 + ±3SD 帶 + 現值百分位）
  --pb 2330                    PB 河流圖（歷史股價淨值比，同上）
  --eps-momentum 2330          EPS 動能（FactSet 跨年度預估上/下修趨勢）
  --target 2330                目標價彙整（CNYES 分析師共識 + Yahoo 目標均價）
  --all 2330                   全部彙整

資料源:
  樂活五線譜 ← Fugle 歷史日K (fallback CNYES)
  PE/PB 河流圖 ← FinMind TaiwanStockPER
  EPS 動能/目標價 ← CNYES estimateProfit / targetPrice + yfinance

回傳: JSON 或 {"error"}。
"""

import asyncio
import json
import statistics
import sys

import numpy as np

# raw-data 工具：tools.* 優先，CLI 獨立跑時退回同層 import
try:
    from tools import cnyes, finmind, fugle, yfinance_data
except ImportError:  # pragma: no cover - CLI standalone fallback
    import cnyes
    import finmind
    import fugle
    import yfinance_data


# ══════════════════════════════════════════════════════════════════
# 數學核心（搬自 math_utils.py，純函式）
# ══════════════════════════════════════════════════════════════════

def _clean(datas: list) -> list[float]:
    """濾掉 None / NaN，轉 float。"""
    out = []
    for d in datas:
        if d is None:
            continue
        try:
            f = float(d)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN
            continue
        out.append(f)
    return out


def mean_reversion(prices: list[float]) -> dict:
    """線性回歸趨勢線 TL + ±1/2/3 SD 帶 + 回歸機率（樂活五線譜核心）。"""
    prices = _clean(prices)
    if len(prices) < 2:
        return {}
    arr = np.array(prices, dtype=float)
    idx = np.arange(1, len(arr) + 1)
    slope, intercept = np.polyfit(idx, arr, 1)
    tl = intercept + idx * slope
    sd = float(np.std(arr - tl, ddof=1)) or 1e-10

    last = float(arr[-1])
    tl_last = float(tl[-1])
    # 七條線的當前值：TL+3SD ... TL ... TL-3SD
    bands = {
        "超極樂觀價位": tl_last + 3 * sd,
        "極樂觀價位": tl_last + 2 * sd,
        "樂觀價位": tl_last + 1 * sd,
        "趨勢價位": tl_last,
        "悲觀價位": tl_last - 1 * sd,
        "極悲觀價位": tl_last - 2 * sd,
        "超極悲觀價位": tl_last - 3 * sd,
    }
    # 回歸機率（logistic 近似常態 CDF）
    z = (last - tl_last) / sd
    cdf = 1.0 / (1.0 + np.exp(-1.702 * z))
    down_prob = float(cdf) * 100
    up_prob = (1.0 - float(cdf)) * 100

    targets = {}
    for label, price in bands.items():
        targets[label] = {
            "price": round(price, 2),
            "diff_pct": round((price - last) / last * 100, 2) if last else None,
        }
    return {
        "current_price": round(last, 2),
        "trend_price": round(tl_last, 2),
        "sd": round(sd, 4),
        "up_prob_pct": round(up_prob, 2),
        "down_prob_pct": round(down_prob, 2),
        "bands": targets,
    }


def quartile(datas: list[float]) -> dict:
    """四分位數 + 平均。"""
    datas = _clean(datas)
    if not datas:
        return {}
    arr = np.array(datas, dtype=float)
    return {
        "q25": round(float(np.percentile(arr, 25)), 2),
        "q50": round(float(np.percentile(arr, 50)), 2),
        "q75": round(float(np.percentile(arr, 75)), 2),
        "mean": round(float(np.mean(arr)), 2),
    }


def std_bands(datas: list[float]) -> dict:
    """中位數為基準的 ±1/2/3 SD 帶（河流圖用）。"""
    datas = _clean(datas)
    if not datas:
        return {}
    arr = np.array(datas, dtype=float)
    tl = float(statistics.median(arr))
    sd = float(np.std(arr - tl, ddof=1)) or 1e-10
    return {
        "TL+3SD": round(tl + 3 * sd, 2),
        "TL+2SD": round(tl + 2 * sd, 2),
        "TL+1SD": round(tl + 1 * sd, 2),
        "TL": round(tl, 2),
        "TL-1SD": round(tl - 1 * sd, 2),
        "TL-2SD": round(tl - 2 * sd, 2),
        "TL-3SD": round(tl - 3 * sd, 2),
    }


def percentile_rank(datas: list[float], value: float) -> float:
    """value 在資料中的百分位（0-100）。"""
    datas = _clean(datas)
    if not datas or value is None:
        return 50.0
    arr = np.array(datas, dtype=float)
    return round(float((arr < value).mean() * 100), 2)


# ══════════════════════════════════════════════════════════════════
# 估值 function（import raw 工具拿資料 → 套公式）
# ══════════════════════════════════════════════════════════════════

async def lohas(symbol: str, years: float = 3.5) -> dict:
    """樂活五線譜。股價序列來自 Fugle 歷史日K，失敗退回 CNYES。"""
    days = int(years * 365)
    res = await fugle.fetch_historical_candles(symbol, days=days)
    closes = []
    if "error" not in res:
        closes = [c.get("close") for c in res.get("data", [])]
    if not closes:  # fallback CNYES
        res = await cnyes.fetch_history(symbol, days=days)
        if "error" not in res:
            closes = [c.get("close") for c in res.get("candles", [])]
    closes = _clean(closes)
    if len(closes) < 60:
        return {"error": f"樂活五線譜資料不足（{len(closes)} 筆）: {symbol}"}
    result = mean_reversion(closes)
    result["symbol"] = symbol
    result["years"] = years
    result["n_points"] = len(closes)
    return result


async def _per_series(symbol: str, field: str) -> tuple[list[float], float | None]:
    """從 FinMind 取 PER 或 PBR 歷史序列 + 最新值。"""
    res = finmind.fetch_per_pbr(symbol)
    if "error" in res:
        return [], None
    rows = res.get("data", [])
    series = _clean([r.get(field) for r in rows])
    latest = series[-1] if series else None
    return series, latest


async def pe_river(symbol: str) -> dict:
    """PE 河流圖：歷史本益比四分位 + ±3SD 帶 + 現值百分位。"""
    series, latest = await _per_series(symbol, "PER")
    if not series:
        return {"error": f"PE 河流圖無資料（需 FinMind token）: {symbol}"}
    return {
        "symbol": symbol,
        "metric": "PER",
        "current": latest,
        "n_points": len(series),
        "quartile": quartile(series),
        "std_bands": std_bands(series),
        "percentile": percentile_rank(series, latest),
    }


async def pb_river(symbol: str) -> dict:
    """PB 河流圖：歷史股價淨值比四分位 + ±3SD 帶 + 現值百分位。"""
    series, latest = await _per_series(symbol, "PBR")
    if not series:
        return {"error": f"PB 河流圖無資料（需 FinMind token）: {symbol}"}
    return {
        "symbol": symbol,
        "metric": "PBR",
        "current": latest,
        "n_points": len(series),
        "quartile": quartile(series),
        "std_bands": std_bands(series),
        "percentile": percentile_rank(series, latest),
    }


async def eps_momentum(symbol: str) -> dict:
    """EPS 動能：FactSet 跨年度預估 EPS 的上/下修趨勢與訊號。"""
    res = await cnyes.fetch_estimate_eps(symbol)
    if "error" in res:
        return res
    items = res.get("data", [])
    # 用各年度 eps_median（缺則 eps_mean）建時間線，依 financial_year 排序
    timeline = []
    for it in items:
        eps = it.get("eps_median") or it.get("eps_mean")
        if eps is None:
            continue
        timeline.append({
            "financial_year": it.get("financial_year"),
            "eps": eps,
            "rate_date": it.get("rate_date"),
            "up": it.get("up"),
            "down": it.get("down"),
            "num_est": it.get("num_est"),
        })
    if len(timeline) < 2:
        return {"error": f"EPS 動能資料不足: {symbol}"}

    # 相鄰年度成長率
    growth = []
    for i in range(1, len(timeline)):
        prev = timeline[i - 1]["eps"]
        cur = timeline[i]["eps"]
        if prev:
            growth.append(round((cur - prev) / abs(prev) * 100, 2))

    # 訊號：看最新一年的上/下修家數
    latest = timeline[-1]
    up = latest.get("up") or 0
    down = latest.get("down") or 0
    if up > down:
        signal = "分析師偏上修"
    elif down > up:
        signal = "分析師偏下修"
    else:
        signal = "中性"

    return {
        "symbol": symbol,
        "timeline": timeline,
        "yoy_growth_pct": growth,
        "latest_up": up,
        "latest_down": down,
        "signal": signal,
    }


async def target_summary(symbol: str) -> dict:
    """目標價彙整：CNYES 分析師共識 + Yahoo(yfinance) 目標均價。"""
    cnyes_res, yahoo_res = await asyncio.gather(
        cnyes.fetch_target_price(symbol),
        yfinance_data.fetch_target(symbol),
    )
    out = {"symbol": symbol, "sources": {}}
    if "error" not in cnyes_res:
        out["sources"]["cnyes"] = {
            "target_mean": cnyes_res.get("target_mean"),
            "target_high": cnyes_res.get("target_high"),
            "target_low": cnyes_res.get("target_low"),
            "num_est": cnyes_res.get("num_est"),
            "last": cnyes_res.get("last"),
            "upside_pct": cnyes_res.get("upside_pct"),
        }
    if "error" not in yahoo_res:
        out["sources"]["yahoo"] = {
            "target_mean": yahoo_res.get("targetMeanPrice"),
            "target_high": yahoo_res.get("targetHighPrice"),
            "target_low": yahoo_res.get("targetLowPrice"),
            "num_est": yahoo_res.get("numberOfAnalystOpinions"),
            "current_price": yahoo_res.get("currentPrice"),
            "recommendation": yahoo_res.get("recommendationKey"),
            "upside_pct": yahoo_res.get("upside_pct"),
        }
    if not out["sources"]:
        return {"error": f"目標價無資料: {symbol}"}
    return out


async def valuation_all(symbol: str, years: float = 3.5) -> dict:
    """全部估值彙整。"""
    lohas_r, pe_r, pb_r, eps_r, target_r = await asyncio.gather(
        lohas(symbol, years),
        pe_river(symbol),
        pb_river(symbol),
        eps_momentum(symbol),
        target_summary(symbol),
    )
    return {
        "symbol": symbol,
        "lohas": lohas_r,
        "pe_river": pe_r,
        "pb_river": pb_r,
        "eps_momentum": eps_r,
        "target": target_r,
    }


_MODES = {
    "lohas": lohas,
    "pe": pe_river,
    "pb": pb_river,
    "eps-momentum": eps_momentum,
    "target": target_summary,
    "all": valuation_all,
}


def _parse_args(argv: list[str]) -> tuple[str, str, float]:
    mode = None
    symbol = None
    years = 3.5
    for flag in _MODES:
        if f"--{flag}" in argv:
            mode = flag
            idx = argv.index(f"--{flag}")
            if idx + 1 < len(argv):
                symbol = argv[idx + 1]
            break
    if "--years" in argv:
        try:
            years = float(argv[argv.index("--years") + 1])
        except (IndexError, ValueError):
            pass
    return mode, symbol, years


async def _run(mode: str, symbol: str, years: float) -> dict:
    if mode in ("lohas", "all"):
        return await _MODES[mode](symbol, years)
    return await _MODES[mode](symbol)


if __name__ == "__main__":
    args = sys.argv[1:]
    mode, symbol, years = _parse_args(args)
    if not mode or not symbol:
        flags = "|".join(f"--{m}" for m in _MODES)
        print(json.dumps({"error": f"用法: python tools/valuation.py [{flags}] SYMBOL [--years 3.5]"},
                         ensure_ascii=False))
        sys.exit(1)

    result = asyncio.run(_run(mode, symbol, years))
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)
