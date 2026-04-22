"""
即時股價查詢服務。

台股：優先鉅亨網爬蟲（即時）→ FinMind tick_snapshot（即時，需 Sponsor）→ yfinance（約 15–20 分鐘延遲）。
美股：yfinance。
查詢時附帶 Google News 前 5 筆相關新聞。
台股代碼支援 4-5 位數字或英數字（如 00637L）。
"""

import asyncio
import logging

import aiohttp
import yfinance as yf

from ..utils.ticker_utils import get_tw_search_tickers, is_taiwan_ticker
from .http import create_session

logger = logging.getLogger(__name__)


def _format_news_section(news_list: list[dict]) -> str:
    """將新聞列表格式化成 Telegram Markdown（精簡 + 日期 + 標題截斷）。"""
    if not news_list:
        return ""
    lines = []
    max_len = 40
    for n in news_list[:5]:
        title = (n.get("title") or "").replace("[", "(").replace("]", ")")
        url = n.get("url", "")
        date_str = n.get("date", "")
        if title and url:
            if len(title) > max_len:
                title = title[: max_len - 1].rstrip() + "…"
            prefix = f"{date_str} " if date_str else ""
            lines.append(f"• {prefix}[{title}]({url})")
    if not lines:
        return ""
    return "\n\n📰 相關新聞\n" + "\n".join(lines)


async def _append_news(price_text: str, ticker: str, name: str, is_tw: bool = True) -> str:
    """在股價訊息後附加相關新聞。"""
    try:
        from .stock_news_fetcher import fetch_stock_news

        news_list = await fetch_stock_news(ticker, name, limit=5, is_tw=is_tw)
        return price_text + _format_news_section(news_list)
    except Exception as e:
        logger.debug("Stock news fetch: %s", e)
        return price_text


async def fetch_price(ticker: str) -> str:
    """
    查詢股價，回傳格式化字串（不含新聞）。

    Args:
        ticker: 股票代碼，如 2330、2330.TW、AAPL

    Returns:
        格式化後的股價訊息，或錯誤訊息。
    """
    ticker = ticker.strip().upper()
    if not ticker:
        return "❌ 請輸入股票代碼，例如：/p 2330"

    # 台股：先試鉅亨網即時，再 FinMind，最後 yfinance（含 00637L 等英數字代碼）
    if is_taiwan_ticker(ticker):
        stock_id = ticker
        # 1. 鉅亨網爬蟲（即時）
        try:
            from .cnyes_quote_scraper import fetch_tw_quote

            async with create_session() as session:
                quote = await fetch_tw_quote(stock_id, session)
                if quote:
                    p = quote["price"]
                    ch = quote.get("change")
                    chp = quote.get("change_pct")
                    name = quote.get("name", stock_id)
                    sign = "📈" if (ch is not None and ch >= 0) else "📉"
                    ch_str = f"{ch:+.2f}" if ch is not None else ""
                    pct_str = f"({chp:+.2f}%)" if chp is not None else ""
                    return f"{sign}{stock_id} {name}\n💰{p:.2f} {ch_str}{pct_str}"
        except Exception as e:
            logger.debug("CNYES quote: %s", e)

        # 2. FinMind 即時（需 Sponsor）
        try:
            from ..config import get_settings
            from .finmind_fetcher import FinMindFetcher

            settings = get_settings()
            if settings.FINMIND_TOKENS:
                async with create_session() as session:
                    fm = FinMindFetcher()
                    snap = await fm.get_tick_snapshot(session, stock_id)
                    if snap:
                        info = await fm.get_stock_info(session, stock_id)
                        name = info.get("name", stock_id)
                        p = snap["close"]
                        ch = snap.get("change_price")
                        chp = snap.get("change_rate")
                        if ch is not None and chp is not None:
                            try:
                                ch = float(ch)
                                chp = float(chp)
                            except (TypeError, ValueError):
                                ch, chp = None, None
                        sign = "📈" if (ch is not None and ch >= 0) else "📉"
                        ch_str = f"{ch:+.2f}" if ch is not None else ""
                        pct_str = f"({chp:+.2f}%)" if chp is not None else ""
                        return f"{sign}{stock_id} {name}\n💰{p:.2f} {ch_str}{pct_str}"
        except Exception as e:
            logger.debug("FinMind tick snapshot: %s", e)

    # 台股：yfinance 先試 .TW，再試 .TWO
    search_tickers = get_tw_search_tickers(ticker) if is_taiwan_ticker(ticker) else [ticker]

    def _get_price(sym: str) -> dict | None:
        try:
            stock = yf.Ticker(sym)
            info = stock.info
            fast = getattr(stock, "fast_info", None)
            price = None
            prev_close = None
            if fast:
                try:
                    price = getattr(fast, "last_price", None) or getattr(
                        fast, "previous_close", None
                    )
                    prev_close = getattr(fast, "previous_close", None)
                except Exception:
                    pass
            if price is None:
                price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price is None and prev_close is None:
                hist = stock.history(period="5d")
                if not hist.empty and "Close" in hist.columns:
                    price = float(hist["Close"].iloc[-1])
                    prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price
            if price is None or price <= 0:
                return None
            name = info.get("shortName") or info.get("longName") or sym
            change = None
            change_pct = None
            if prev_close and prev_close > 0:
                change = price - prev_close
                change_pct = (change / prev_close) * 100
            return {
                "ticker": sym,
                "name": name,
                "price": float(price),
                "change": change,
                "change_pct": change_pct,
            }
        except Exception as e:
            logger.debug("Price fetch %s: %s", sym, e)
            return None

    for sym in search_tickers:
        result = await asyncio.to_thread(_get_price, sym)
        if result:
            name = result["name"]
            # 台股：從 FinMind 取得中文名稱
            if is_taiwan_ticker(ticker) or sym.endswith(".TW") or sym.endswith(".TWO"):
                stock_id = ticker if is_taiwan_ticker(ticker) else sym.split(".")[0]
                try:
                    from ..config import get_settings
                    from .finmind_fetcher import FinMindFetcher

                    settings = get_settings()
                    if settings.FINMIND_TOKENS:
                        async with create_session() as session:
                            fm = FinMindFetcher()
                            info = await fm.get_stock_info(session, stock_id)
                            if info.get("name"):
                                name = info["name"]
                except Exception as e:
                    logger.debug("FinMind name fetch: %s", e)
            p = result["price"]
            ch = result["change"]
            chp = result["change_pct"]
            if ch is not None and chp is not None:
                sign = "📈" if ch >= 0 else "📉"
                ch_str = f"{ch:+.2f}" if isinstance(ch, float) else str(ch)
                pct_str = f"({chp:+.2f}%)"
            else:
                sign = "📊"
                ch_str = ""
                pct_str = ""
            delay_note = (
                "\n（約 15–20 分鐘延遲）"
                if (is_taiwan_ticker(ticker) or sym.endswith(".TW") or sym.endswith(".TWO"))
                else ""
            )
            stock_id = ticker if is_taiwan_ticker(ticker) else sym.split(".")[0]
            is_tw = is_taiwan_ticker(ticker) or sym.endswith(".TW") or sym.endswith(".TWO")
            return (
                f"{sign}{result['ticker']} {name}\n💰{p:.2f} {ch_str}{pct_str}{delay_note}"
            )

    return f"❌ 找不到 {ticker} 的股價資料"
