#!/usr/bin/env python3
"""
雙均線策略 — MA20 金叉/死叉 MA60

策略：減少假訊號，用長短均線交叉
- 買入：MA20 上穿 MA60（黃金交叉）
- 賣出：MA20 下穿 MA60（死亡交叉）

執行：python scripts/backtest_ma_cross.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

TICKER = "0050.TW"
YEARS = 10
MA_SHORT = 20
MA_LONG = 60


def fetch_data(ticker: str, years: int) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=years * 365)
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, auto_adjust=True)
    if hist.empty or len(hist) < MA_LONG + 10:
        raise ValueError("資料不足")
    return hist[["Close"]].dropna()


def run_backtest(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["MA20"] = df["Close"].rolling(MA_SHORT).mean()
    df["MA60"] = df["Close"].rolling(MA_LONG).mean()
    df = df.dropna()

    closes = df["Close"].tolist()
    ma20s = df["MA20"].tolist()
    ma60s = df["MA60"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    trades = []
    position = None

    for i in range(1, n):
        close = closes[i]
        ma20 = ma20s[i]
        ma60 = ma60s[i]
        prev_ma20 = ma20s[i - 1]
        prev_ma60 = ma60s[i - 1]
        date = dates[i]

        # 死亡交叉：MA20 下穿 MA60
        if position:
            if prev_ma20 >= prev_ma60 and ma20 < ma60:
                ret_pct = (close - position["buy_price"]) / position["buy_price"] * 100
                trades.append({
                    "buy_date": position["buy_date"],
                    "sell_date": date,
                    "return_pct": ret_pct,
                    "hold_days": (date - position["buy_date"]).days,
                })
                position = None
            continue

        # 黃金交叉：MA20 上穿 MA60
        if not position and prev_ma20 <= prev_ma60 and ma20 > ma60:
            position = {"buy_date": date, "buy_price": close}

    if position:
        ret_pct = (closes[-1] - position["buy_price"]) / position["buy_price"] * 100
        trades.append({
            "buy_date": position["buy_date"],
            "sell_date": dates[-1],
            "return_pct": ret_pct,
            "hold_days": (dates[-1] - position["buy_date"]).days,
        })

    total_ret = 1.0
    for t in trades:
        total_ret *= 1 + t["return_pct"] / 100
    strategy_ret = (total_ret - 1) * 100

    start_price = closes[0]
    end_price = closes[-1]
    buy_hold_ret = (end_price - start_price) / start_price * 100

    return {
        "strategy_ret": strategy_ret,
        "buy_hold_ret": buy_hold_ret,
        "trades": trades,
        "total_days": n,
        "dates": dates,
    }


def print_report(result: dict) -> None:
    r = result
    years_span = r["total_days"] / 252
    s_cagr = ((1 + r["strategy_ret"] / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
    b_cagr = ((1 + r["buy_hold_ret"] / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0

    print("\n" + "=" * 60)
    print(f"  雙均線策略 MA{MA_SHORT}/MA{MA_LONG} — {TICKER} 近{YEARS}年")
    print("=" * 60)
    print(f"  交易次數：{len(r['trades'])} 筆")
    print("-" * 60)
    print(f"  {'策略':<25} {'累計報酬':>14} {'年化報酬':>14}")
    print(f"  {'─'*25} {'─'*14} {'─'*14}")
    print(f"  {'MA20/MA60 金叉死叉':<25} {r['strategy_ret']:>+13.2f}% {s_cagr:>+13.2f}%")
    print(f"  {'買入持有':<25} {r['buy_hold_ret']:>+13.2f}% {b_cagr:>+13.2f}%")
    print("-" * 60)
    diff = r["strategy_ret"] - r["buy_hold_ret"]
    status = "領先" if diff > 0 else "落後"
    print(f"  雙均線 vs 買入持有：{diff:+.2f}% （{status} {abs(diff):.2f}%）")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    result = run_backtest(df)
    print_report(result)


if __name__ == "__main__":
    main()
