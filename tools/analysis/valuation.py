"""valuation — 估值計算（CLI + import 雙入口）

本工具不直接打 API，而是 import raw 層工具（raw/cnyes、raw/finmind、raw/fugle、
raw/yfinance_data、raw/uanalyze）拿原始資料，套用估值公式。數學核心（線性回歸均值回歸、
標準差帶、四分位、百分位、DCF 時間加權折現）純 numpy/math。

估值方式:
  --lohas 2330 [--years 3.5]   樂活五線譜（股價線性回歸 ±3SD 七線 + 機率）
  --pe 2330                    PE 河流圖（FinMind 歷史本益比四分位 + ±3SD 帶 + 現值百分位）
  --pb 2330                    PB 河流圖（FinMind 歷史股價淨值比，同上）
  --eps-momentum 2330          EPS 動能（FactSet 跨年度預估上/下修趨勢）
  --target 2330                目標價彙整（CNYES 分析師共識 + Yahoo 目標均價）
  --dcf 2330 [--csv]           時間加權動態 DCF 估值（UAnalyze 法人共識 EPS/營收；--csv 可多檔輸出）
  --pe-band 2330               PE/PB Band（UAnalyze 長歷史 + 同業本益比中位數 + 現值百分位）
  --all 2330                   全部彙整（不含 dcf/pe-band，那兩者需 UAnalyze 登入）

資料源:
  樂活五線譜 ← Fugle 歷史日K
  PE/PB 河流圖 ← FinMind TaiwanStockPER
  EPS 動能/目標價 ← CNYES estimateProfit / targetPrice + yfinance
  DCF / PE-PB Band ← UAnalyze（raw/uanalyze 各端點；需 UANALYZE_EMAIL/PASSWORD）

回傳: JSON 或 {"error"}。
"""

import asyncio
import json
import math
import statistics
import sys
from datetime import datetime

import numpy as np

# raw-data 工具：tools.raw.* 優先，CLI 獨立跑（python tools/analysis/valuation.py）時
# tools package 不在 sys.path，補上 repo 根再 import。
try:
    from tools.raw import cnyes, finmind, fugle, uanalyze as raw_uanalyze, yfinance_data
except ImportError:  # pragma: no cover - CLI standalone fallback
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    from tools.raw import cnyes, finmind, fugle, uanalyze as raw_uanalyze, yfinance_data


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
    """樂活五線譜。股價序列來自 Fugle 歷史日K。"""
    days = int(years * 365)
    res = await fugle.fetch_historical_candles(symbol, days=days)
    closes = []
    if "error" not in res:
        closes = [c.get("close") for c in res.get("data", [])]
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


# ══════════════════════════════════════════════════════════════════
# UAnalyze 估值：DCF（時間加權動態折現）+ PE/PB Band
# 取數 call raw/uanalyze（登入在 raw 層處理），計算在此。
# ══════════════════════════════════════════════════════════════════

# DCF 固定參數
WACC = 0.12
TERMINAL_G = 0.03
REV_SENSITIVITY = 0.4
LAMBDA_BASE = 0.50
LAMBDA_N_STEP = 0.12
N_MAX_CONVERGE = 5
N_MAX_DIVERGE = 3


def _compute_dcf(
    eps_hist: dict,
    eps_fore: dict,
    rev_gap_pct_str: str,
    rev_gap_val: float,
    current_month: int = 8,
    base_year: int | None = None,
) -> tuple:
    """時間加權動態 DCF 純數學核心。回 (base_ttm, v_2025, v_2026E, v_2027E,
    far_fore_yr, far_fore_eps, confidence_level, intrinsic_val)。base_year 可注入以便測試。
    """
    if base_year is None:
        base_year = datetime.now().year - 1
    BASE_YEAR = base_year

    sorted_fore_yrs = sorted(eps_fore.keys())
    v_2025 = eps_hist[max(eps_hist.keys())]
    v_2026E = eps_fore[sorted_fore_yrs[0]]
    v_2027E = eps_fore.get(BASE_YEAR + 2)

    rev_multiplier = math.exp(REV_SENSITIVITY * (rev_gap_val / 100.0)) if rev_gap_pct_str != "-" else 1.0

    w_hist = (12 - (current_month - 1)) / 12.0
    w_fore = (current_month - 1) / 12.0
    base_ttm = (w_hist * v_2025 + w_fore * v_2026E) * rev_multiplier

    far_fore_yr = sorted_fore_yrs[-1]
    n_known_years = max(1, far_fore_yr - BASE_YEAR)
    last_known_fore_yr = far_fore_yr
    last_known_eps = eps_fore[far_fore_yr]

    prev_fore_eps = eps_fore.get(last_known_fore_yr - 1)
    if prev_fore_eps is not None and prev_fore_eps > 0 and last_known_eps > 0:
        marginal_yoy = (last_known_eps / prev_fore_eps) - 1.0
    elif last_known_eps > 0:
        cagr_base = max(1.0, base_ttm) if base_ttm > 0 else max(1.0, abs(v_2026E))
        marginal_yoy = (last_known_eps / cagr_base) - 1.0
    else:
        marginal_yoy = 0.0

    if base_ttm > 0 and last_known_eps > 0 and n_known_years > 0:
        overall_cagr = (last_known_eps / base_ttm) ** (1.0 / n_known_years) - 1.0
    else:
        overall_cagr = marginal_yoy

    rev_multiplier = math.exp(REV_SENSITIVITY * (rev_gap_val / 100.0)) if rev_gap_pct_str != "-" else 1.0
    raw_marginal_g = max(0.0, marginal_yoy) * rev_multiplier
    raw_cagr_g = max(0.0, overall_cagr) * rev_multiplier

    raw_decay_start_g = min(raw_marginal_g, max(raw_cagr_g, 0.50))
    raw_decay_start_g = min(raw_decay_start_g, 0.50)

    confidence_level = f"高 (法人完全直連 N={n_known_years})"
    decay_start_g = raw_decay_start_g
    lambda_decay = LAMBDA_BASE + LAMBDA_N_STEP * (3 - min(3, n_known_years))

    if marginal_yoy > 0.50:
        lambda_decay += max(0.0, (marginal_yoy - 0.50) * 0.50)

    if n_known_years <= 2:
        if raw_marginal_g > 0.50:
            decay_start_g = min(raw_marginal_g * 0.40, 0.50)
            confidence_level = "⚠️ 低 (N≤2極端外推打折)"
            lambda_decay = max(lambda_decay, 0.70)
        else:
            confidence_level = "中低 (N≤2)"

    current_eps = base_ttm
    pv_sum = 0.0
    for yr in range(1, 11):
        target_year = BASE_YEAR + yr
        if target_year in eps_fore and target_year <= last_known_fore_yr:
            current_eps = eps_fore[target_year]
        else:
            t = target_year - last_known_fore_yr
            curr_g = TERMINAL_G + (decay_start_g - TERMINAL_G) * math.exp(-lambda_decay * t)
            curr_g = max(curr_g, TERMINAL_G)
            current_eps = current_eps * (1.0 + curr_g)
        pv_sum += current_eps / ((1.0 + WACC) ** yr)

    tv_10 = (current_eps * (1.0 + TERMINAL_G)) / (WACC - TERMINAL_G)
    pv_tv = tv_10 / ((1.0 + WACC) ** 10)
    intrinsic_val = round(pv_sum + pv_tv, 2)

    return base_ttm, v_2025, v_2026E, v_2027E, far_fore_yr, eps_fore[far_fore_yr], confidence_level, intrinsic_val


def _parse_eps_consensus(raw: dict) -> tuple[dict, dict]:
    """從 raw eps_revenue_consensus 的 ua50187_cp(EPS) 拆 (eps_hist, eps_fore)。"""
    eps_hist: dict[int, float] = {}
    eps_fore: dict[int, float] = {}
    eps_data = (raw.get("ua50187_cp") or {}).get("Data") or {} if isinstance(raw, dict) else {}
    for k, v in eps_data.items():
        if isinstance(v, (int, float)):
            clean_k = str(k).replace("(f)", "").strip()
            try:
                yr = int(clean_k)
            except ValueError:
                continue
            (eps_fore if "(f)" in str(k) else eps_hist)[yr] = float(v)
    return eps_hist, eps_fore


def _parse_revenue_gap(raw: dict) -> tuple[str, str, float]:
    """從 raw revenue_tracking 的 ua70306_cp 取最後一月當營收超預期 gap。"""
    diff = (raw.get("ua70306_cp") or {}).get("Data") or {} if isinstance(raw, dict) else {}
    if isinstance(diff, dict) and diff:
        m_keys = sorted(diff.keys())
        last = diff[m_keys[-1]]
        if isinstance(last, (int, float)):
            trend = " | ".join(
                f"{m}月:{diff[m]:+.1f}%" if isinstance(diff[m], (int, float)) else f"{m}月:-"
                for m in m_keys[-3:]
            )
            return f"{last:+.1f}%", trend, float(last)
    return "-", "-", 0.0


async def dcf_valuation(symbol: str) -> dict:
    """時間加權動態 DCF 估值。取數 call raw/uanalyze，計算用 _compute_dcf。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    eps_raw, rev_raw = await asyncio.gather(
        raw_uanalyze.fetch_raw_eps_revenue_consensus(symbol),
        raw_uanalyze.fetch_raw_revenue_tracking(symbol),
    )
    if isinstance(eps_raw, dict) and "error" in eps_raw:
        return {"error": f"{symbol} 無法取得法人共識 EPS：{eps_raw['error']}"}
    eps_hist, eps_fore = _parse_eps_consensus(eps_raw)
    if not eps_hist or not eps_fore:
        return {"error": f"{symbol} EPS 資料不足，無法計算 DCF"}
    rev_gap_pct_str, _rev_trend, rev_gap_val = (
        _parse_revenue_gap(rev_raw) if isinstance(rev_raw, dict) and "error" not in rev_raw else ("-", "-", 0.0)
    )

    (base_ttm, v_2025, v_2026E, _v_2027E, far_fore_yr, far_fore_eps,
     confidence_level, intrinsic_val) = _compute_dcf(eps_hist, eps_fore, rev_gap_pct_str, rev_gap_val)

    forward_val_1yr = round(intrinsic_val * (1.0 + WACC) - v_2026E, 2)
    return {
        "symbol": symbol,
        "每股合理內在價值": intrinsic_val,
        "1年後前瞻合理價值": forward_val_1yr,
        "當前時間加權基期": round(base_ttm, 2),
        "營收動能": rev_gap_pct_str,
        "2025實際獲利": round(v_2025, 2),
        "2026E": round(v_2026E, 2),
        "最遠預估年份及獲利": f"{far_fore_yr}E:{round(far_fore_eps, 2)}元",
        "信心度": confidence_level,
    }


def _ratio_series(raw: dict) -> tuple[list[float], float | None]:
    """從 raw historical_per/pbr 的單一 uaXXXXX_cp.Data 取 (序列, 最新值)。"""
    if not isinstance(raw, dict):
        return [], None
    for row in raw.values():
        if isinstance(row, dict) and isinstance(row.get("Data"), dict):
            series = _clean(list(row["Data"].values()))
            return series, (series[-1] if series else None)
    return [], None


async def pe_pb_band(symbol: str) -> dict:
    """PE/PB Band：UAnalyze 長歷史 PE/PB + 同業本益比中位數 + 現值歷史百分位。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}
    per_raw, pbr_raw, band_raw = await asyncio.gather(
        raw_uanalyze.fetch_raw_historical_per(symbol),
        raw_uanalyze.fetch_raw_historical_pbr(symbol),
        raw_uanalyze.fetch_raw_pe_band(symbol),
    )
    pe_series, pe_latest = _ratio_series(per_raw if isinstance(per_raw, dict) and "error" not in per_raw else {})
    pb_series, pb_latest = _ratio_series(pbr_raw if isinstance(pbr_raw, dict) and "error" not in pbr_raw else {})
    if not pe_series and not pb_series:
        return {"error": f"查無 {symbol} 的 PE/PB Band 資料"}

    # 同業本益比中位數（PE_Band.refdata）
    peer_median = None
    if isinstance(band_raw, dict) and "error" not in band_raw:
        refdata = band_raw.get("refdata")
        if isinstance(refdata, dict):
            peer_median = refdata.get("peer_pe_median") or refdata.get("同業本益比中位數")

    out: dict = {"symbol": symbol}
    if pe_series:
        out["pe"] = {
            "latest": pe_latest,
            "n_points": len(pe_series),
            "quartile": quartile(pe_series),
            "std_bands": std_bands(pe_series),
            "percentile_in_history": percentile_rank(pe_series, pe_latest),
            "peer_median": peer_median,
        }
    if pb_series:
        out["pb"] = {
            "latest": pb_latest,
            "n_points": len(pb_series),
            "quartile": quartile(pb_series),
            "std_bands": std_bands(pb_series),
            "percentile_in_history": percentile_rank(pb_series, pb_latest),
        }
    return out


_MODES = {
    "lohas": lohas,
    "pe": pe_river,
    "pb": pb_river,
    "eps-momentum": eps_momentum,
    "target": target_summary,
    "dcf": dcf_valuation,
    "pe-band": pe_pb_band,
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


# ── DCF → CSV（併自舊 dcf_to_csv.py）：--dcf <代號...> --csv ────────────────
import csv as _csv  # noqa: E402
import io as _io  # noqa: E402

DEFAULT_MULTI_CONCURRENCY = 4
_DCF_CSV_FIELDS = [
    "symbol", "每股合理內在價值", "1年後前瞻合理價值", "當前時間加權基期", "營收動能",
    "2025實際獲利", "2026E", "最遠預估年份及獲利", "信心度", "error",
]


def _parse_symbols(raw_args: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for chunk in raw_args:
        for part in chunk.split(","):
            s = part.strip().upper()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


async def _dcf_csv_rows(symbols: list[str], concurrency: int) -> list[dict]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(sym: str) -> dict:
        async with sem:
            try:
                res = await dcf_valuation(sym)
            except Exception as e:  # noqa: BLE001
                res = {"error": f"{sym} DCF 計算失敗：{e}"}
        row = {k: "" for k in _DCF_CSV_FIELDS}
        row["symbol"] = sym
        if "error" in res:
            row["error"] = res["error"]
        else:
            for k, v in res.items():
                if k in row:
                    row[k] = v
        return row

    return await asyncio.gather(*[_one(s) for s in symbols])


def _rows_to_csv(rows: list[dict]) -> str:
    buf = _io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=_DCF_CSV_FIELDS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


if __name__ == "__main__":
    args = sys.argv[1:]

    # --dcf 特例：支援 --csv 多檔輸出（併自 dcf_to_csv）。
    if "--dcf" in args and "--csv" in args:
        idx = args.index("--dcf")
        # --dcf 後、遇到其他 --flag 前的都是代號
        syms_raw: list[str] = []
        for a in args[idx + 1:]:
            if a.startswith("--"):
                break
            syms_raw.append(a)
        symbols = _parse_symbols(syms_raw)
        if not symbols:
            print(json.dumps({"error": "用法: python tools/analysis/valuation.py --dcf <代號...> --csv [--out FILE]"},
                             ensure_ascii=False))
            sys.exit(1)
        concurrency = DEFAULT_MULTI_CONCURRENCY
        if "--concurrency" in args:
            try:
                concurrency = int(args[args.index("--concurrency") + 1])
            except (IndexError, ValueError):
                pass
        rows = asyncio.run(_dcf_csv_rows(symbols, concurrency))
        csv_text = _rows_to_csv(rows)
        if "--out" in args:
            try:
                out_path = args[args.index("--out") + 1]
            except IndexError:
                out_path = "dcf.csv"
            with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(csv_text)
            ok = sum(1 for r in rows if not r["error"])
            print(f"已寫入 {out_path}：成功 {ok} 檔，失敗 {len(rows) - ok} 檔", file=sys.stderr)
        else:
            sys.stdout.write(csv_text)
        sys.exit(0 if any(not r["error"] for r in rows) else 1)

    mode, symbol, years = _parse_args(args)
    if not mode or not symbol:
        flags = "|".join(f"--{m}" for m in _MODES)
        print(json.dumps({"error": f"用法: python tools/analysis/valuation.py [{flags}] SYMBOL [--years 3.5] [--dcf ... --csv]"},
                         ensure_ascii=False))
        sys.exit(1)

    result = asyncio.run(_run(mode, symbol, years))
    print(json.dumps(result, ensure_ascii=False))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)
