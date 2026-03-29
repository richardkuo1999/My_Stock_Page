"""Ticker format utilities for Taiwan and other markets."""
import re

# 台股代碼：4-5 位數字，或 4-5 位數字 + 1 個英文字母（如 00637L）
TW_TICKER_RE = re.compile(r"^[0-9]{4,5}[A-Z]?$", re.IGNORECASE)


def is_taiwan_ticker(ticker: str) -> bool:
    """
    判斷是否為台股代碼（需加 .TW 或 .TWO 才能向 Yahoo 查詢）。

    範例：2330, 0050, 00637L, 00633L
    """
    if not ticker or "." in ticker:
        return False
    return bool(TW_TICKER_RE.match(ticker.strip().upper()))


def get_tw_search_tickers(ticker: str) -> list[str]:
    """取得 yfinance 查詢用的台股代碼列表（先 .TW 再 .TWO）。"""
    t = ticker.strip().upper()
    return [f"{t}.TW", f"{t}.TWO"]
