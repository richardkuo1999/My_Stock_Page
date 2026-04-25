"""盤中走勢圖產生。用 yfinance 抓 1m K 線，繪成 PNG。"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import yfinance as yf

from ..utils.ticker_utils import get_tw_search_tickers, is_taiwan_ticker
from .http import create_session

logger = logging.getLogger(__name__)


def _fetch_intraday(ticker: str):
    search = get_tw_search_tickers(ticker) if is_taiwan_ticker(ticker) else [ticker]
    for sym in search:
        try:
            tk = yf.Ticker(sym)
            df = tk.history(period="5d", interval="1m")
            if df is None or df.empty:
                continue
            last_day = df.index[-1].date()
            intraday = df[df.index.date == last_day]
            if intraday.empty:
                continue
            prev_close = None
            try:
                daily = tk.history(period="10d", interval="1d")
                if daily is not None and not daily.empty:
                    prior = daily[daily.index.date < last_day]
                    if not prior.empty:
                        prev_close = float(prior["Close"].iloc[-1])
            except Exception:
                pass
            return sym, intraday, prev_close
        except Exception as e:
            logger.debug("intraday fetch %s: %s", sym, e)
    return None, None, None


def _render(
    sym: str,
    name: str,
    df,
    is_tw: bool,
    prev_close: float | None,
    live_price: float | None,
) -> str:
    if is_tw:
        try:
            if df.index.tz is None:
                df = df.tz_localize("UTC").tz_convert("Asia/Taipei")
            else:
                df = df.tz_convert("Asia/Taipei")
        except Exception:
            pass
    close = df["Close"].copy()
    if live_price and live_price > 0:
        import pandas as pd

        now_ts = pd.Timestamp.now(tz="Asia/Taipei" if is_tw else close.index.tz)
        session_end = None
        if is_tw:
            d = close.index[-1].date()
            session_end = pd.Timestamp(
                datetime(d.year, d.month, d.day, 13, 30), tz="Asia/Taipei"
            )
        append_ts = min(now_ts, session_end) if session_end else now_ts
        if append_ts > close.index[-1]:
            close.loc[append_ts] = float(live_price)
            close = close.sort_index()
    last = float(live_price) if live_price and live_price > 0 else float(close.iloc[-1])
    baseline = prev_close if prev_close and prev_close > 0 else float(close.iloc[0])
    change = last - baseline
    pct = (change / baseline * 100) if baseline else 0.0
    color = "#d62728" if change >= 0 else "#2ca02c"

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(close.index, close, linewidth=1.5, color=color)
    fill_base = min(close.min(), baseline)
    ax.fill_between(close.index, close, fill_base, alpha=0.1, color=color)
    if prev_close:
        ax.axhline(prev_close, color="gray", linestyle="--", linewidth=0.8, alpha=0.7)
    day = df.index[-1].strftime("%Y-%m-%d")
    ax.set_title(f"{sym} {name} — {day}   {last:.2f} ({change:+.2f} / {pct:+.2f}%)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    if is_tw:
        import pandas as pd

        last_ts = df.index[-1]
        session_day = last_ts.date()
        start = pd.Timestamp(
            datetime(session_day.year, session_day.month, session_day.day, 9, 0),
            tz="Asia/Taipei",
        )
        end = pd.Timestamp(
            datetime(session_day.year, session_day.month, session_day.day, 13, 30),
            tz="Asia/Taipei",
        )
        ax.set_xlim(start, end)
        ax.xaxis.set_major_locator(mdates.HourLocator(tz="Asia/Taipei"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="Asia/Taipei"))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.3)
    plt.tight_layout()

    fd, path = tempfile.mkstemp(
        prefix=f"intraday_{sym.replace('.', '_')}_",
        suffix=".png",
        dir=tempfile.gettempdir(),
    )
    os.close(fd)
    plt.savefig(path, dpi=110)
    plt.close(fig)
    return path


async def _fetch_live_tw_price(stock_id: str) -> float | None:
    try:
        from .cnyes_quote_scraper import fetch_tw_quote

        async with create_session() as session:
            q = await fetch_tw_quote(stock_id, session)
            if q and q.get("price"):
                return float(q["price"])
    except Exception as e:
        logger.debug("live tw price: %s", e)
    return None


async def render_intraday_chart(ticker: str, name: str = "") -> str | None:
    """回傳 PNG 檔路徑；失敗回傳 None。"""
    ticker = ticker.strip().upper()
    try:
        sym, df, prev_close = await asyncio.to_thread(_fetch_intraday, ticker)
        if df is None or df.empty:
            return None
        is_tw = is_taiwan_ticker(ticker) or sym.endswith(".TW") or sym.endswith(".TWO")
        live_price = None
        if is_tw:
            stock_id = ticker if is_taiwan_ticker(ticker) else sym.split(".")[0]
            live_price = await _fetch_live_tw_price(stock_id)
        return await asyncio.to_thread(
            _render, sym, name or sym, df, is_tw, prev_close, live_price
        )
    except Exception as e:
        logger.warning("render_intraday_chart failed: %s", e)
        return None
