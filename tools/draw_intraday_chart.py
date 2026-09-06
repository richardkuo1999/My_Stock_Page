"""draw_intraday_chart — 繪製盤中分時走勢折線圖並回傳圖片路徑

用法: python tools/draw_intraday_chart.py SYMBOL
回傳: JSON {"image_path": "/tmp/intraday_SYMBOL.png"}

資料來源：Fugle intraday/candles（每分鐘 OHLCV）+ intraday/quote（前收）。
純繪圖工具，本身不呼叫任何 AI。
"""

import asyncio
import json
import logging
import os
import sys
import tempfile

import httpx
import matplotlib

matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock"
DEFAULT_TIMEFRAME = "1"  # 1-minute candles
DEFAULT_TIMEOUT = 15.0
_TZ = "Asia/Taipei"


def _get_fugle_api_key() -> str | None:
    key = os.getenv("FUGLE_API_KEY", "").strip().strip('"').strip("'")
    return key if key else None


def _parse_candles(candles: list[dict]) -> pd.DataFrame:
    """Turn Fugle intraday candle rows into a time-indexed OHLCV frame.

    Each row looks like {"date": ISO8601, "open", "high", "low", "close",
    "volume", ...}. Returns an empty frame for empty input.
    """
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    rename = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df = df.rename(columns=rename)
    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].astype(float)
    return df


async def _fetch_intraday(symbol: str) -> tuple[list[dict], float | None, str]:
    """Fetch per-minute candles + previous close + name from Fugle.

    Returns (candles, prev_close, name). candles is [] on failure.
    """
    key = _get_fugle_api_key()
    if not key:
        return [], None, ""

    headers = {"X-API-KEY": key, "Accept": "application/json"}
    candles: list[dict] = []
    prev_close: float | None = None
    name = ""

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            c_url = f"{FUGLE_BASE}/intraday/candles/{symbol}"
            r = await client.get(
                c_url, headers=headers, params={"timeframe": DEFAULT_TIMEFRAME}
            )
            if r.status_code == 200:
                candles = r.json().get("data", []) or []

            # Previous close + name come from the quote endpoint.
            q_url = f"{FUGLE_BASE}/intraday/quote/{symbol}"
            rq = await client.get(q_url, headers=headers)
            if rq.status_code == 200:
                q = rq.json()
                prev = q.get("previousClose") or q.get("referencePrice")
                if prev is not None:
                    prev_close = float(prev)
                name = q.get("name", "") or ""
    except Exception as e:
        logger.debug("Fugle intraday fetch error for %s: %s", symbol, e)

    return candles, prev_close, name


def _render_chart(
    df: pd.DataFrame, symbol: str, name: str, prev_close: float | None
) -> str:
    """Render an intraday line chart (price line + fill + prev-close ref).

    Colour follows Taiwan convention (red up / green down) relative to the
    baseline, which is the previous close when known, else the first tick.
    """
    if df is None or len(df) < 2:
        n = 0 if df is None else len(df)
        raise ValueError(f"資料不足，僅有 {n} 筆")

    close = df["Close"]
    last = float(close.iloc[-1])
    baseline = (
        prev_close if prev_close and prev_close > 0 else float(close.iloc[0])
    )
    change = last - baseline
    pct = (change / baseline * 100) if baseline else 0.0
    color = "#e74c3c" if change >= 0 else "#2ecc71"

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(close.index, close, linewidth=1.5, color=color)
    fill_base = min(float(close.min()), baseline)
    ax.fill_between(close.index, close, fill_base, alpha=0.1, color=color)
    if prev_close and prev_close > 0:
        ax.axhline(
            prev_close, color="gray", linestyle="--", linewidth=0.8, alpha=0.7
        )

    day = df.index[-1].strftime("%Y-%m-%d")
    title_name = name or symbol
    ax.set_title(
        f"{symbol} {title_name} — {day}   "
        f"{last:.2f} ({change:+.2f} / {pct:+.2f}%)"
    )
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.3)
    plt.tight_layout()

    fd, path = tempfile.mkstemp(
        prefix=f"intraday_{symbol}_", suffix=".png"
    )
    os.close(fd)
    plt.savefig(path, dpi=110)
    plt.close(fig)
    return path


async def draw(symbol: str) -> dict:
    """Draw an intraday time-series chart for a Taiwan stock.

    Args:
        symbol: Taiwan stock symbol, e.g. '2330'

    Returns:
        dict with 'image_path' on success, or 'error' on failure.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}

    candles, prev_close, name = await _fetch_intraday(symbol)
    df = _parse_candles(candles)
    if df.empty:
        return {"error": f"找不到股票代號 {symbol} 的盤中資料"}

    try:
        # matplotlib 繪圖是同步 CPU 工作，offload 到 thread 避免卡住事件迴圈
        path = await asyncio.to_thread(
            _render_chart, df, symbol, name, prev_close
        )
        return {"image_path": path}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("Intraday chart render error for %s: %s", symbol, e)
        return {"error": f"繪圖失敗: {e}"}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(
            json.dumps(
                {"error": "用法: python tools/draw_intraday_chart.py SYMBOL"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    result = asyncio.run(draw(args[0]))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
