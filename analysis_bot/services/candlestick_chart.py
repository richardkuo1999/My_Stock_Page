"""日 K 線圖（TradingView lightweight-charts + Playwright headless 截圖）。

優先透過 yfinance 抓取日線數據 → 組 HTML → Chromium 渲染 → 截圖 PNG。
"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from playwright.async_api import async_playwright

from ..utils.ticker_utils import get_tw_search_tickers, is_taiwan_ticker

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90


_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  body {{ margin: 0; background: #ffffff; font-family: -apple-system, "Helvetica Neue", Arial; }}
  #wrap {{ width: 1100px; padding: 12px 16px 8px; }}
  #title {{ font-size: 15px; color: #222; margin: 4px 2px 8px; font-weight: 600; }}
  #chart {{ width: 1080px; height: 560px; }}
</style></head>
<body>
<div id="wrap">
  <div id="title">{title}</div>
  <div id="chart"></div>
</div>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script>
const candles = {candles};
const ma5 = {ma5};
const ma20 = {ma20};
const ma60 = {ma60};
const volumes = {volumes};

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
  layout: {{ background: {{ color: '#ffffff' }}, textColor: '#333' }},
  grid: {{ vertLines: {{ color: '#eee' }}, horzLines: {{ color: '#eee' }} }},
  rightPriceScale: {{ borderColor: '#ccc' }},
  timeScale: {{ borderColor: '#ccc', timeVisible: false, secondsVisible: false, barSpacing: 8 }},
  width: 1080, height: 560,
}});

const candleSeries = chart.addCandlestickSeries({{
  upColor: '#e74c3c', downColor: '#2ecc71',
  borderUpColor: '#e74c3c', borderDownColor: '#2ecc71',
  wickUpColor: '#e74c3c', wickDownColor: '#2ecc71',
}});
candleSeries.setData(candles);

chart.addLineSeries({{ color: '#2980b9', lineWidth: 1, lastValueVisible: false, priceLineVisible: false }}).setData(ma5);
chart.addLineSeries({{ color: '#f39c12', lineWidth: 1, lastValueVisible: false, priceLineVisible: false }}).setData(ma20);
chart.addLineSeries({{ color: '#8e44ad', lineWidth: 1, lastValueVisible: false, priceLineVisible: false }}).setData(ma60);

const volSeries = chart.addHistogramSeries({{
  priceFormat: {{ type: 'volume' }},
  priceScaleId: '',
}});
volSeries.priceScale().applyOptions({{ scaleMargins: {{ top: 0.78, bottom: 0 }} }});
volSeries.setData(volumes);

chart.timeScale().fitContent();
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
    import pandas as pd

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


def _build_payload(sym: str, name: str, df) -> dict:
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[df["Volume"] > 0]
    if df.empty:
        raise ValueError("no OHLCV data")
    try:
        if df.index.tz is not None:
            df = df.tz_convert("Asia/Taipei")
    except Exception:
        pass

    ma5 = df["Close"].rolling(5).mean()
    ma20 = df["Close"].rolling(20).mean()
    ma60 = df["Close"].rolling(60).mean()

    disp = df.iloc[-_LOOKBACK_DAYS:]

    candles, vols, ma5_l, ma20_l, ma60_l = [], [], [], [], []
    for ts, row in disp.iterrows():
        t = {"year": ts.year, "month": ts.month, "day": ts.day}
        o, h, lo, c, v = (
            float(row["Open"]), float(row["High"]), float(row["Low"]),
            float(row["Close"]), float(row["Volume"]),
        )
        candles.append({"time": t, "open": o, "high": h, "low": lo, "close": c})
        color = "#e74c3c" if c >= o else "#2ecc71"
        vols.append({"time": t, "value": v, "color": color})
        m5 = ma5.loc[ts]
        m20 = ma20.loc[ts]
        m60 = ma60.loc[ts]
        if not _isnan(m5):
            ma5_l.append({"time": t, "value": float(m5)})
        if not _isnan(m20):
            ma20_l.append({"time": t, "value": float(m20)})
        if not _isnan(m60):
            ma60_l.append({"time": t, "value": float(m60)})

    last = float(disp["Close"].iloc[-1])
    first = float(disp["Close"].iloc[0])
    chg = last - first
    pct = (chg / first * 100) if first else 0.0
    trend = "▲" if chg >= 0 else "▼"
    title = (
        f"{sym} {name}  {trend} {last:.2f}  ({chg:+.2f} / {pct:+.2f}%)   "
        f"近 {len(disp)} 個交易日 · {disp.index[-1].strftime('%Y-%m-%d')}"
    )
    return {
        "title": title,
        "candles": candles,
        "ma5": ma5_l,
        "ma20": ma20_l,
        "ma60": ma60_l,
        "volumes": vols,
    }


def _isnan(x) -> bool:
    try:
        return x != x
    except Exception:
        return True


async def _screenshot(payload: dict) -> str:
    html = _HTML_TEMPLATE.format(
        title=payload["title"],
        candles=json.dumps(payload["candles"]),
        ma5=json.dumps(payload["ma5"]),
        ma20=json.dumps(payload["ma20"]),
        ma60=json.dumps(payload["ma60"]),
        volumes=json.dumps(payload["volumes"]),
    )
    fd, path = tempfile.mkstemp(prefix="kline_", suffix=".png", dir=tempfile.gettempdir())
    os.close(fd)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(viewport={"width": 1120, "height": 640})
            page = await context.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_function("window.__ready__ === true", timeout=10_000)
            await page.wait_for_timeout(300)
            elem = await page.query_selector("#wrap")
            await (elem or page).screenshot(path=path)
        finally:
            await browser.close()
    return path


async def render_candlestick_chart(ticker: str, name: str = "") -> str | None:
    ticker = ticker.strip().upper()
    try:
        sym, df = await asyncio.to_thread(_fetch_daily, ticker)
        if df is None or df.empty:
            return None
        payload = await asyncio.to_thread(_build_payload, sym, name or sym, df)
        return await _screenshot(payload)
    except Exception as e:
        logger.warning("render_candlestick_chart failed: %s", e)
        return None
