"""日 K 線圖（TradingView lightweight-charts + Playwright headless 截圖）。

優先透過 yfinance 抓取日線數據 → 組 HTML → Chromium 渲染 → 截圖 PNG。
支援自訂 MA 週期、RSI、MACD 等技術指標。
"""

import asyncio
import json
import logging
import multiprocessing
import os
import tempfile
from string import Template

import pandas as pd
import yfinance as yf

from ..utils.ticker_utils import get_tw_search_tickers, is_taiwan_ticker

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90

# 預設 MA 週期
DEFAULT_MA_PERIODS = [5, 20, 60]

# MA 線顏色
MA_COLORS = [
    "#2980b9",  # 藍
    "#f39c12",  # 橘
    "#8e44ad",  # 紫
    "#e74c3c",  # 紅
    "#27ae60",  # 綠
    "#1abc9c",  # 青
]


def _build_html_template(
    ma_count: int = 3,
    show_rsi: bool = False,
    show_macd: bool = False,
    show_kd: bool = False,
    show_bb: bool = False,
    show_dmi: bool = False,
) -> str:
    """動態產生 HTML 模板（使用 $var 佔位符，避免 JS/CSS 大括號衝突）。"""
    main_height = 420

    # MA 線 JS
    ma_js_lines = []
    for i in range(ma_count):
        color = MA_COLORS[i % len(MA_COLORS)]
        ma_js_lines.append(
            f"chart.addLineSeries({{ color: '{color}', lineWidth: 1, "
            f"lastValueVisible: false, priceLineVisible: false }}).setData(maLines[{i}]);"
        )
    ma_js = "\n".join(ma_js_lines)

    # Bollinger Bands — 疊加在主圖
    bb_js = ""
    if show_bb:
        bb_js = """
const bbUpper = chart.addLineSeries({ color: '#e67e22', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
bbUpper.setData(bbUpperData);
const bbMiddle = chart.addLineSeries({ color: '#e67e22', lineWidth: 1, lastValueVisible: false, priceLineVisible: false });
bbMiddle.setData(bbMiddleData);
const bbLower = chart.addLineSeries({ color: '#e67e22', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
bbLower.setData(bbLowerData);
"""

    # RSI 區塊
    rsi_html = ""
    rsi_js = ""
    if show_rsi:
        rsi_html = '<div class="sub-label">RSI(14) — <span style="color:#9b59b6">RSI</span></div><div id="rsi-chart" style="width: 1080px; height: 120px;"></div>'
        rsi_js = """
const rsiChart = LightweightCharts.createChart(document.getElementById('rsi-chart'), {
  layout: { background: { color: '#ffffff' }, textColor: '#333' },
  grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
  rightPriceScale: { borderColor: '#ccc' },
  timeScale: { borderColor: '#ccc', timeVisible: false, visible: false },
  width: 1080, height: 120,
});
const rsiSeries = rsiChart.addLineSeries({ color: '#9b59b6', lineWidth: 1.5, lastValueVisible: true, priceLineVisible: false });
rsiSeries.setData(rsiData);
const rsiOverbought = rsiChart.addLineSeries({ color: '#e74c3c', lineWidth: 0.5, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
rsiOverbought.setData(rsiData.map(d => ({time: d.time, value: 70})));
const rsiOversold = rsiChart.addLineSeries({ color: '#27ae60', lineWidth: 0.5, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
rsiOversold.setData(rsiData.map(d => ({time: d.time, value: 30})));
rsiChart.timeScale().fitContent();
chart.timeScale().subscribeVisibleLogicalRangeChange(range => { rsiChart.timeScale().setVisibleLogicalRange(range); });
"""

    # KD 區塊
    kd_html = ""
    kd_js = ""
    if show_kd:
        kd_html = '<div class="sub-label">KD(9,3,3) — <span style="color:#2980b9">K</span> / <span style="color:#e74c3c">D</span></div><div id="kd-chart" style="width: 1080px; height: 120px;"></div>'
        kd_js = """
const kdChart = LightweightCharts.createChart(document.getElementById('kd-chart'), {
  layout: { background: { color: '#ffffff' }, textColor: '#333' },
  grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
  rightPriceScale: { borderColor: '#ccc' },
  timeScale: { borderColor: '#ccc', timeVisible: false, visible: false },
  width: 1080, height: 120,
});
const kSeries = kdChart.addLineSeries({ color: '#2980b9', lineWidth: 1.5, lastValueVisible: true, priceLineVisible: false });
kSeries.setData(kdKData);
const dSeries = kdChart.addLineSeries({ color: '#e74c3c', lineWidth: 1.5, lastValueVisible: true, priceLineVisible: false });
dSeries.setData(kdDData);
const kdOB = kdChart.addLineSeries({ color: '#aaa', lineWidth: 0.5, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
kdOB.setData(kdKData.map(d => ({time: d.time, value: 80})));
const kdOS = kdChart.addLineSeries({ color: '#aaa', lineWidth: 0.5, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
kdOS.setData(kdKData.map(d => ({time: d.time, value: 20})));
kdChart.timeScale().fitContent();
chart.timeScale().subscribeVisibleLogicalRangeChange(range => { kdChart.timeScale().setVisibleLogicalRange(range); });
"""

    # MACD 區塊
    macd_html = ""
    macd_js = ""
    if show_macd:
        macd_html = '<div class="sub-label">MACD(12,26,9) — <span style="color:#2980b9">MACD</span> / <span style="color:#e74c3c">Signal</span> / Histogram</div><div id="macd-chart" style="width: 1080px; height: 140px;"></div>'
        macd_js = """
const macdChart = LightweightCharts.createChart(document.getElementById('macd-chart'), {
  layout: { background: { color: '#ffffff' }, textColor: '#333' },
  grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
  rightPriceScale: { borderColor: '#ccc' },
  timeScale: { borderColor: '#ccc', timeVisible: false, visible: false },
  width: 1080, height: 140,
});
const macdLineSeries = macdChart.addLineSeries({ color: '#2980b9', lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false });
macdLineSeries.setData(macdLine);
const signalSeries = macdChart.addLineSeries({ color: '#e74c3c', lineWidth: 1, lastValueVisible: false, priceLineVisible: false });
signalSeries.setData(signalLine);
const histSeries = macdChart.addHistogramSeries({ lastValueVisible: false, priceLineVisible: false });
histSeries.setData(macdHist);
macdChart.timeScale().fitContent();
chart.timeScale().subscribeVisibleLogicalRangeChange(range => { macdChart.timeScale().setVisibleLogicalRange(range); });
"""

    # DMI 區塊
    dmi_html = ""
    dmi_js = ""
    if show_dmi:
        dmi_html = '<div class="sub-label">DMI(14) — <span style="color:#27ae60">+DI</span> / <span style="color:#e74c3c">-DI</span> / <span style="color:#f39c12">ADX</span></div><div id="dmi-chart" style="width: 1080px; height: 130px;"></div>'
        dmi_js = """
const dmiChart = LightweightCharts.createChart(document.getElementById('dmi-chart'), {
  layout: { background: { color: '#ffffff' }, textColor: '#333' },
  grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
  rightPriceScale: { borderColor: '#ccc' },
  timeScale: { borderColor: '#ccc', timeVisible: false, visible: false },
  width: 1080, height: 130,
});
const plusDiSeries = dmiChart.addLineSeries({ color: '#27ae60', lineWidth: 1.5, lastValueVisible: true, priceLineVisible: false });
plusDiSeries.setData(dmiPlusDi);
const minusDiSeries = dmiChart.addLineSeries({ color: '#e74c3c', lineWidth: 1.5, lastValueVisible: true, priceLineVisible: false });
minusDiSeries.setData(dmiMinusDi);
const adxSeries = dmiChart.addLineSeries({ color: '#f39c12', lineWidth: 1.5, lastValueVisible: true, priceLineVisible: false });
adxSeries.setData(dmiAdx);
dmiChart.timeScale().fitContent();
chart.timeScale().subscribeVisibleLogicalRangeChange(range => { dmiChart.timeScale().setVisibleLogicalRange(range); });
"""

    # 指標標籤
    indicator_labels = []
    if show_bb:
        indicator_labels.append("BB(20,2)")
    if show_rsi:
        indicator_labels.append("RSI(14)")
    if show_kd:
        indicator_labels.append("KD(9,3,3)")
    if show_macd:
        indicator_labels.append("MACD(12,26,9)")
    if show_dmi:
        indicator_labels.append("DMI(14)")
    ma_prefix = "MA: $ma_label" if ma_count > 0 else ""
    sep = "  |  " if ma_count > 0 and indicator_labels else ""
    indicators_line = f"{ma_prefix}{sep}{' · '.join(indicator_labels)}" if (ma_count > 0 or indicator_labels) else ""

    # 使用 $var 佔位符 — JS/CSS 的 {} 不再需要跳脫
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  body {{ margin: 0; background: #ffffff; font-family: -apple-system, "Helvetica Neue", Arial; }}
  #wrap {{ width: 1100px; padding: 12px 16px 8px; }}
  #title {{ font-size: 15px; color: #222; margin: 4px 2px 8px; font-weight: 600; }}
  #indicators {{ font-size: 11px; color: #666; margin: 0 2px 4px; }}
  .sub-label {{ font-size: 11px; color: #555; margin: 8px 2px 2px; font-weight: 600; }}
  #chart {{ width: 1080px; height: {main_height}px; }}
</style></head>
<body>
<div id="wrap">
  <div id="title">$title</div>
  <div id="indicators">{indicators_line}</div>
  <div id="chart"></div>
  {rsi_html}
  {kd_html}
  {macd_html}
  {dmi_html}
</div>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script>
const candles = $candles;
const maLines = $ma_lines;
const volumes = $volumes;
const rsiData = $rsi_data;
const macdLine = $macd_line;
const signalLine = $signal_line;
const macdHist = $macd_hist;
const kdKData = $kd_k;
const kdDData = $kd_d;
const bbUpperData = $bb_upper;
const bbMiddleData = $bb_middle;
const bbLowerData = $bb_lower;
const dmiPlusDi = $dmi_plus_di;
const dmiMinusDi = $dmi_minus_di;
const dmiAdx = $dmi_adx;

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
  layout: {{ background: {{ color: '#ffffff' }}, textColor: '#333' }},
  grid: {{ vertLines: {{ color: '#eee' }}, horzLines: {{ color: '#eee' }} }},
  rightPriceScale: {{ borderColor: '#ccc' }},
  timeScale: {{ borderColor: '#ccc', timeVisible: false, secondsVisible: false, barSpacing: 8 }},
  width: 1080, height: {main_height},
}});

const candleSeries = chart.addCandlestickSeries({{
  upColor: '#e74c3c', downColor: '#2ecc71',
  borderUpColor: '#e74c3c', borderDownColor: '#2ecc71',
  wickUpColor: '#e74c3c', wickDownColor: '#2ecc71',
}});
candleSeries.setData(candles);

{ma_js}

{bb_js}

const volSeries = chart.addHistogramSeries({{
  priceFormat: {{ type: 'volume' }},
  priceScaleId: '',
}});
volSeries.priceScale().applyOptions({{ scaleMargins: {{ top: 0.78, bottom: 0 }} }});
volSeries.setData(volumes);

chart.timeScale().fitContent();

{rsi_js}
{kd_js}
{macd_js}
{dmi_js}

window.__ready__ = true;
</script>
</body></html>
"""


def _fetch_daily(ticker: str):
    search = get_tw_search_tickers(ticker) if is_taiwan_ticker(ticker) else [ticker]
    for sym in search:
        try:
            tk = yf.Ticker(sym)
            df = tk.history(period="8mo", interval="1d")
            if df is None or df.empty:
                continue
            _patch_missing_close(tk, df)
            return sym, df
        except Exception as e:
            logger.debug("daily fetch %s: %s", sym, e)
    return None, None


def _patch_missing_close(tk, df) -> None:
    """yfinance 偶爾最新日線 Close=NaN（TW 盤後延遲），用 1m 資料補最後收盤。"""
    last_row = df.iloc[-1]
    if not _isnan(last_row.get("Close")):
        return
    try:
        m = tk.history(period="2d", interval="1m")
        if m is None or m.empty:
            return
        last_day = df.index[-1].date()
        same_day = m[m.index.date == last_day]
        if same_day.empty:
            return
        last_close = float(same_day["Close"].dropna().iloc[-1])
        df.loc[df.index[-1], "Close"] = last_close
        if _isnan(last_row.get("Open")):
            df.loc[df.index[-1], "Open"] = float(same_day["Open"].dropna().iloc[0])
        if _isnan(last_row.get("High")):
            df.loc[df.index[-1], "High"] = float(same_day["High"].dropna().max())
        if _isnan(last_row.get("Low")):
            df.loc[df.index[-1], "Low"] = float(same_day["Low"].dropna().min())
    except Exception as e:
        logger.debug("patch close via 1m: %s", e)


def _compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """計算 RSI 指標。"""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _compute_macd(
    closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """計算 MACD 指標。回傳 (macd_line, signal_line, histogram)。"""
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _compute_kd(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k_period: int = 9, k_smooth: int = 3, d_smooth: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """計算 KD 隨機指標。回傳 (%K, %D)。"""
    lowest = low.rolling(k_period, min_periods=k_period).min()
    highest = high.rolling(k_period, min_periods=k_period).max()
    rsv = (close - lowest) / (highest - lowest).replace(0, float("nan")) * 100
    k = rsv.ewm(com=k_smooth - 1, adjust=False).mean()
    d = k.ewm(com=d_smooth - 1, adjust=False).mean()
    return k, d


def _compute_bollinger(
    closes: pd.Series, period: int = 20, num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """計算布林通道。回傳 (upper, middle, lower)。"""
    middle = closes.rolling(period, min_periods=period).mean()
    std = closes.rolling(period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def _compute_dmi(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """計算 DMI 指標。回傳 (+DI, -DI, ADX)。"""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    adx = dx.ewm(span=period, adjust=False).mean()
    return plus_di, minus_di, adx


def _build_payload(
    sym: str,
    name: str,
    df,
    ma_periods: list[int] | None = None,
    show_rsi: bool = False,
    show_macd: bool = False,
    show_kd: bool = False,
    show_bb: bool = False,
    show_dmi: bool = False,
) -> dict:
    """建構圖表資料 payload。"""
    if ma_periods is None:
        ma_periods = DEFAULT_MA_PERIODS

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[df["Volume"] > 0]
    if df.empty:
        raise ValueError("no OHLCV data")
    try:
        if df.index.tz is not None:
            df = df.tz_convert("Asia/Taipei")
    except Exception:
        pass

    # 計算所有 MA
    ma_series = {}
    for period in ma_periods:
        ma_series[period] = df["Close"].rolling(period).mean()

    # 計算 RSI
    rsi_series = _compute_rsi(df["Close"]) if show_rsi else pd.Series(dtype=float)

    # 計算 MACD
    if show_macd:
        macd_line, signal_line, macd_hist = _compute_macd(df["Close"])
    else:
        macd_line = signal_line = macd_hist = pd.Series(dtype=float)

    # 計算 KD
    if show_kd:
        kd_k, kd_d = _compute_kd(df["High"], df["Low"], df["Close"])
    else:
        kd_k = kd_d = pd.Series(dtype=float)

    # 計算布林通道
    if show_bb:
        bb_upper, bb_middle, bb_lower = _compute_bollinger(df["Close"])
    else:
        bb_upper = bb_middle = bb_lower = pd.Series(dtype=float)

    # 計算 DMI
    if show_dmi:
        dmi_plus, dmi_minus, dmi_adx = _compute_dmi(df["High"], df["Low"], df["Close"])
    else:
        dmi_plus = dmi_minus = dmi_adx = pd.Series(dtype=float)

    disp = df.iloc[-_LOOKBACK_DAYS:]

    candles, vols = [], []
    ma_lists = {p: [] for p in ma_periods}
    rsi_data = []
    macd_line_data, signal_line_data, macd_hist_data = [], [], []
    kd_k_data, kd_d_data = [], []
    bb_upper_data, bb_middle_data, bb_lower_data = [], [], []
    dmi_plus_data, dmi_minus_data, dmi_adx_data = [], [], []

    for ts, row in disp.iterrows():
        t = {"year": ts.year, "month": ts.month, "day": ts.day}
        o, h, lo, c, v = (
            float(row["Open"]), float(row["High"]), float(row["Low"]),
            float(row["Close"]), float(row["Volume"]),
        )
        candles.append({"time": t, "open": o, "high": h, "low": lo, "close": c})
        color = "#e74c3c" if c >= o else "#2ecc71"
        vols.append({"time": t, "value": v, "color": color})

        # MA lines
        for period in ma_periods:
            val = ma_series[period].loc[ts]
            if not _isnan(val):
                ma_lists[period].append({"time": t, "value": float(val)})

        # RSI
        if show_rsi and ts in rsi_series.index:
            rsi_val = rsi_series.loc[ts]
            if not _isnan(rsi_val):
                rsi_data.append({"time": t, "value": float(rsi_val)})

        # MACD
        if show_macd and ts in macd_line.index:
            ml = macd_line.loc[ts]
            sl = signal_line.loc[ts]
            mh = macd_hist.loc[ts]
            if not _isnan(ml):
                macd_line_data.append({"time": t, "value": float(ml)})
            if not _isnan(sl):
                signal_line_data.append({"time": t, "value": float(sl)})
            if not _isnan(mh):
                hist_color = "#e74c3c" if mh >= 0 else "#2ecc71"
                macd_hist_data.append({"time": t, "value": float(mh), "color": hist_color})

        # KD
        if show_kd and ts in kd_k.index:
            kv = kd_k.loc[ts]
            dv = kd_d.loc[ts]
            if not _isnan(kv):
                kd_k_data.append({"time": t, "value": float(kv)})
            if not _isnan(dv):
                kd_d_data.append({"time": t, "value": float(dv)})

        # Bollinger Bands
        if show_bb and ts in bb_upper.index:
            bu, bm, bl = bb_upper.loc[ts], bb_middle.loc[ts], bb_lower.loc[ts]
            if not _isnan(bu):
                bb_upper_data.append({"time": t, "value": float(bu)})
            if not _isnan(bm):
                bb_middle_data.append({"time": t, "value": float(bm)})
            if not _isnan(bl):
                bb_lower_data.append({"time": t, "value": float(bl)})

        # DMI
        if show_dmi and ts in dmi_plus.index:
            dp, dm, da = dmi_plus.loc[ts], dmi_minus.loc[ts], dmi_adx.loc[ts]
            if not _isnan(dp):
                dmi_plus_data.append({"time": t, "value": float(dp)})
            if not _isnan(dm):
                dmi_minus_data.append({"time": t, "value": float(dm)})
            if not _isnan(da):
                dmi_adx_data.append({"time": t, "value": float(da)})

    last = float(disp["Close"].iloc[-1])
    first = float(disp["Close"].iloc[0])
    chg = last - first
    pct = (chg / first * 100) if first else 0.0
    trend = "▲" if chg >= 0 else "▼"
    title = (
        f"{sym} {name}  {trend} {last:.2f}  ({chg:+.2f} / {pct:+.2f}%)   "
        f"近 {len(disp)} 個交易日 · {disp.index[-1].strftime('%Y-%m-%d')}"
    )

    ma_label = "/".join(str(p) for p in ma_periods)

    return {
        "title": title,
        "ma_label": ma_label,
        "candles": candles,
        "ma_lines": [ma_lists[p] for p in ma_periods],
        "volumes": vols,
        "rsi_data": rsi_data,
        "macd_line": macd_line_data,
        "signal_line": signal_line_data,
        "macd_hist": macd_hist_data,
        "kd_k": kd_k_data,
        "kd_d": kd_d_data,
        "bb_upper": bb_upper_data,
        "bb_middle": bb_middle_data,
        "bb_lower": bb_lower_data,
        "dmi_plus_di": dmi_plus_data,
        "dmi_minus_di": dmi_minus_data,
        "dmi_adx": dmi_adx_data,
        "ma_periods": ma_periods,
        "show_rsi": show_rsi,
        "show_macd": show_macd,
        "show_kd": show_kd,
        "show_bb": show_bb,
        "show_dmi": show_dmi,
    }


def _isnan(x) -> bool:
    try:
        return x != x
    except Exception:
        return True


def _screenshot_in_subprocess(html: str, path: str) -> None:
    """Run in a separate process — gets its own event loop with full subprocess support."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(viewport={"width": 1120, "height": 640})
            page = ctx.new_page()
            page.set_content(html, wait_until="networkidle")
            page.wait_for_function("window.__ready__ === true", timeout=10_000)
            page.wait_for_timeout(300)
            elem = page.query_selector("#wrap")
            (elem or page).screenshot(path=path)
        finally:
            browser.close()


async def _screenshot(payload: dict) -> str:
    """渲染圖表並截圖。"""
    template = _build_html_template(
        ma_count=len(payload["ma_periods"]),
        show_rsi=payload["show_rsi"],
        show_macd=payload["show_macd"],
        show_kd=payload["show_kd"],
        show_bb=payload["show_bb"],
        show_dmi=payload["show_dmi"],
    )

    html = Template(template).safe_substitute(
        title=payload["title"],
        ma_label=payload["ma_label"],
        candles=json.dumps(payload["candles"]),
        ma_lines=json.dumps(payload["ma_lines"]),
        volumes=json.dumps(payload["volumes"]),
        rsi_data=json.dumps(payload["rsi_data"]),
        macd_line=json.dumps(payload["macd_line"]),
        signal_line=json.dumps(payload["signal_line"]),
        macd_hist=json.dumps(payload["macd_hist"]),
        kd_k=json.dumps(payload["kd_k"]),
        kd_d=json.dumps(payload["kd_d"]),
        bb_upper=json.dumps(payload["bb_upper"]),
        bb_middle=json.dumps(payload["bb_middle"]),
        bb_lower=json.dumps(payload["bb_lower"]),
        dmi_plus_di=json.dumps(payload["dmi_plus_di"]),
        dmi_minus_di=json.dumps(payload["dmi_minus_di"]),
        dmi_adx=json.dumps(payload["dmi_adx"]),
    )

    # 計算截圖高度
    height = 500
    if payload["show_rsi"]:
        height += 130
    if payload["show_kd"]:
        height += 130
    if payload["show_macd"]:
        height += 150
    if payload["show_dmi"]:
        height += 140

    fd, path = tempfile.mkstemp(prefix="kline_", suffix=".png", dir=tempfile.gettempdir())
    os.close(fd)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_in_process, html, path)
    return path


def _run_in_process(html: str, path: str) -> None:
    proc = multiprocessing.Process(target=_screenshot_in_subprocess, args=(html, path))
    proc.start()
    proc.join(timeout=30)
    if proc.exitcode != 0:
        raise RuntimeError(f"screenshot subprocess failed (exit={proc.exitcode})")


async def render_candlestick_chart(
    ticker: str,
    name: str = "",
    ma_periods: list[int] | None = None,
    show_rsi: bool = False,
    show_macd: bool = False,
    show_kd: bool = False,
    show_bb: bool = False,
    show_dmi: bool = False,
) -> str | None:
    """渲染 K 線圖。

    Args:
        ticker: 股票代碼
        name: 股票名稱
        ma_periods: 自訂 MA 週期列表，如 [5, 10, 20]。None 使用預設 [5, 20, 60]
        show_rsi: 是否顯示 RSI(14) 指標
        show_macd: 是否顯示 MACD(12,26,9) 指標
        show_kd: 是否顯示 KD(9,3,3) 隨機指標
        show_bb: 是否顯示布林通道 BB(20,2)
        show_dmi: 是否顯示 DMI(14) 趨向指標

    Returns:
        截圖檔案路徑，或 None（失敗時）
    """
    ticker = ticker.strip().upper()
    try:
        sym, df = await asyncio.to_thread(_fetch_daily, ticker)
        if df is None or df.empty:
            return None
        payload = await asyncio.to_thread(
            _build_payload, sym, name or sym, df,
            ma_periods, show_rsi, show_macd, show_kd, show_bb, show_dmi,
        )
        return await _screenshot(payload)
    except Exception as e:
        logger.warning("render_candlestick_chart failed: %s", e)
        return None
