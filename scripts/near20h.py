"""
near20h.py — 找出靠近 20 日前高（5% 以內）的台灣上市櫃股票

使用方式：
    python scripts/near20h.py
    python scripts/near20h.py --threshold 3   # 改成 3% 以內
    python scripts/near20h.py --min-lots 500  # 至少 500 張
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass

import aiohttp
import yfinance as yf

TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
ORDINARY_RE = re.compile(r"^\d{4}$")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; near20h/1.0)"}
TIMEOUT = aiohttp.ClientTimeout(total=30)


@dataclass
class NearHighResult:
    ticker: str
    name: str
    close: float
    high20: float
    distance_pct: float  # (high20 - close) / high20 * 100
    volume_lots: int
    market: str


async def _fetch_twse(session: aiohttp.ClientSession) -> list[dict]:
    try:
        async with session.get(TWSE_URL, headers=HEADERS, timeout=TIMEOUT, ssl=False) as r:
            if r.status != 200:
                print(f"[WARN] TWSE API status {r.status}", file=sys.stderr)
                return []
            data = await r.json(content_type=None)
        out = []
        for item in data:
            code = item.get("Code", "")
            if not ORDINARY_RE.match(code):
                continue
            try:
                vol = int(item.get("TradeVolume", "0").replace(",", ""))
                out.append({"ticker": code, "name": item.get("Name", "").strip(),
                            "volume_shares": vol, "market": "TWSE"})
            except (ValueError, TypeError):
                continue
        return out
    except Exception as e:
        print(f"[WARN] TWSE fetch error: {e}", file=sys.stderr)
        return []


async def _fetch_tpex(session: aiohttp.ClientSession) -> list[dict]:
    try:
        async with session.get(TPEX_URL, headers=HEADERS, timeout=TIMEOUT, ssl=False) as r:
            if r.status != 200:
                print(f"[WARN] TPEx API status {r.status}", file=sys.stderr)
                return []
            data = await r.json(content_type=None)
        out = []
        for item in data:
            code = item.get("SecuritiesCompanyCode", "")
            if not ORDINARY_RE.match(code):
                continue
            try:
                vol = int(item.get("TradingShares", "0").replace(",", ""))
                out.append({"ticker": code, "name": item.get("CompanyName", "").strip(),
                            "volume_shares": vol, "market": "TPEx"})
            except (ValueError, TypeError):
                continue
        return out
    except Exception as e:
        print(f"[WARN] TPEx fetch error: {e}", file=sys.stderr)
        return []


async def fetch_all_stocks(min_lots: int) -> list[dict]:
    min_shares = min_lots * 1000
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        twse, tpex = await asyncio.gather(_fetch_twse(session), _fetch_tpex(session))
    all_stocks = twse + tpex
    if min_shares > 0:
        all_stocks = [s for s in all_stocks if s["volume_shares"] >= min_shares]
    print(f"[INFO] {len(all_stocks)} stocks after volume filter (>= {min_lots} 張)", file=sys.stderr)
    return all_stocks


def scan_near_high(
    stocks: list[dict],
    threshold_pct: float,
) -> list[NearHighResult]:
    if not stocks:
        return []

    yf_tickers = []
    stock_map = {}
    for s in stocks:
        suffix = ".TW" if s["market"] == "TWSE" else ".TWO"
        yf_t = f"{s['ticker']}{suffix}"
        yf_tickers.append(yf_t)
        stock_map[yf_t] = s

    print(f"[INFO] Downloading {len(yf_tickers)} tickers from yfinance...", file=sys.stderr)
    hist = yf.download(
        yf_tickers,
        period="2mo",
        group_by="ticker",
        threads=True,
        progress=False,
    )

    results = []
    for yf_t in yf_tickers:
        try:
            if len(yf_tickers) == 1:
                df = hist
            else:
                df = hist[yf_t]

            high = df["High"].dropna().astype(float)
            close = df["Close"].dropna().astype(float)
            if len(high) < 20 or len(close) < 1:
                continue

            high20 = float(high.iloc[-20:].max())
            last_close = float(close.iloc[-1])
            if high20 <= 0:
                continue

            dist = (high20 - last_close) / high20 * 100
            if dist < 0 or dist > threshold_pct:
                continue

            s = stock_map[yf_t]
            results.append(NearHighResult(
                ticker=s["ticker"],
                name=s["name"],
                close=last_close,
                high20=high20,
                distance_pct=dist,
                volume_lots=s["volume_shares"] // 1000,
                market=s["market"],
            ))
        except Exception:
            continue

    results.sort(key=lambda r: r.distance_pct)
    return results


def print_results(results: list[NearHighResult], threshold_pct: float) -> None:
    if not results:
        print(f"無符合條件的股票（距 20 日高點 ≤ {threshold_pct}%）")
        return

    print(f"\n靠近 20 日前高（距離 ≤ {threshold_pct}%）：共 {len(results)} 檔\n")
    print(f"{'代號':<6} {'名稱':<10} {'收盤':>7} {'20日高':>8} {'距離':>7} {'成交量':>7} {'市場':<5}")
    print("-" * 58)
    for r in results:
        print(
            f"{r.ticker:<6} {r.name[:8]:<10} "
            f"{r.close:>7.2f} {r.high20:>8.2f} "
            f"{r.distance_pct:>6.1f}% "
            f"{r.volume_lots:>6}張 "
            f"{r.market}"
        )


async def main(threshold_pct: float, min_lots: int) -> None:
    stocks = await fetch_all_stocks(min_lots)
    results = scan_near_high(stocks, threshold_pct)
    print_results(results, threshold_pct)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="找出靠近 20 日前高的台灣股票")
    parser.add_argument("--threshold", type=float, default=5.0, help="距高點百分比上限（預設 5）")
    parser.add_argument("--min-lots", type=int, default=0, help="最低成交量（張，預設 0 不限）")
    args = parser.parse_args()

    asyncio.run(main(args.threshold, args.min_lots))
