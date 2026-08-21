"""draw_kchart — 繪製 K 線圖並回傳圖片路徑
用法: python tools/draw_kchart.py SYMBOL [--period N]
回傳: JSON {"image_path": "/tmp/kchart_SYMBOL.png"}
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta

import httpx
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import mplfinance as mpf
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"
DEFAULT_PERIOD = 60
DEFAULT_TIMEOUT = 15.0
MA_PERIODS = [5, 20, 60]


def _get_fugle_api_key() -> str | None:
    key = os.getenv("FUGLE_API_KEY", "").strip().strip('"').strip("'")
    return key if key else None


async def _fetch_historical(symbol: str, period: int) -> pd.DataFrame | None:
    """Fetch historical daily candles from Fugle API."""
    key = _get_fugle_api_key()
    if not key:
        return None

    # Request extra days for MA calculation (need MA60 to display from day 1)
    extra_days = max(MA_PERIODS) + 30  # buffer for weekends/holidays
    end_date = datetime.now()
    start_date = end_date - timedelta(days=period + extra_days)

    url = f"{FUGLE_BASE}/historical/candles/{symbol}"
    params = {
        "from": start_date.strftime("%Y-%m-%d"),
        "to": end_date.strftime("%Y-%m-%d"),
        "timeframe": "D",
        "fields": "open,high,low,close,volume",
        "sort": "asc",
    }
    headers = {"X-API-KEY": key, "Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                logger.debug("Fugle candles %s: HTTP %d", symbol, r.status_code)
                return None
            data = r.json()
            candles = data.get("data", [])
            if not candles:
                return None

            df = pd.DataFrame(candles)
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            df = df.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
            return df
    except Exception as e:
        logger.debug("Fugle candles error for %s: %s", symbol, e)
        return None


def _render_chart(df: pd.DataFrame, symbol: str, period: int) -> str:
    """Render K-line chart with mplfinance and save as PNG."""
    # Take only the requested period for display
    display_df = df.tail(period)

    if len(display_df) < 5:
        raise ValueError(f"資料不足，僅有 {len(display_df)} 筆")

    # mplfinance style - Taiwan style (red=up, green=down)
    mc = mpf.make_marketcolors(
        up="#e74c3c", down="#2ecc71",
        edge={"up": "#e74c3c", "down": "#2ecc71"},
        wick={"up": "#e74c3c", "down": "#2ecc71"},
        volume={"up": "#e74c3c", "down": "#2ecc71"},
    )
    style = mpf.make_mpf_style(marketcolors=mc, gridstyle="-", gridcolor="#f0f0f0")

    # Create temp file
    fd, path = tempfile.mkstemp(prefix=f"kchart_{symbol}_", suffix=".png")
    os.close(fd)

    # Plot
    mpf.plot(
        display_df,
        type="candle",
        style=style,
        mav=tuple(MA_PERIODS),
        volume=True,
        title=f"{symbol} 日K ({len(display_df)}日)",
        figsize=(12, 6),
        savefig=dict(fname=path, dpi=100, bbox_inches="tight"),
    )

    return path


async def draw(symbol: str, period: int = DEFAULT_PERIOD) -> dict:
    """Draw K-line chart for a stock.

    Args:
        symbol: Taiwan stock symbol, e.g. '2330'
        period: Number of trading days to display

    Returns:
        dict with 'image_path' key on success, or 'error' key on failure
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}

    df = await _fetch_historical(symbol, period)
    if df is None or df.empty:
        return {"error": f"找不到股票代號 {symbol} 的歷史資料"}

    try:
        path = _render_chart(df, symbol, period)
        return {"image_path": path}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("Chart render error for %s: %s", symbol, e)
        return {"error": f"繪圖失敗: {e}"}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "用法: python tools/draw_kchart.py SYMBOL [--period N]"}, ensure_ascii=False))
        sys.exit(1)

    symbol = args[0]
    period = DEFAULT_PERIOD
    if "--period" in args:
        try:
            period = int(args[args.index("--period") + 1])
        except (IndexError, ValueError):
            pass

    result = asyncio.run(draw(symbol, period))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
