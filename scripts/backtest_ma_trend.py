#!/usr/bin/env python3
"""
趨勢跟隨策略 — MA60 均線策略

策略：順勢而為，上升趨勢持有、下跌趨勢空手
- 買入：收盤價站上 MA60
- 賣出：收盤價跌破 MA60

在長期上升趨勢中，大部分時間持有；在熊市時提早出場，減少虧損。

執行：python scripts/backtest_ma_trend.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

TICKER = "0050.TW"
YEARS = 10
MA_DAYS = 60


def fetch_data(ticker: str, years: int) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=years * 365)
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, auto_adjust=True)
    if hist.empty or len(hist) < MA_DAYS + 10:
        raise ValueError(f"資料不足")
    return hist[["Close"]].dropna()


def run_backtest(df: pd.DataFrame) -> tuple[list[dict], float]:
    df = df.copy()
    df["MA60"] = df["Close"].rolling(MA_DAYS).mean()
    df = df.dropna()

    closes = df["Close"].tolist()
    ma60s = df["MA60"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    trades = []
    position = None
    cash_ret = 1.0  # 空手時現金不變

    for i in range(1, n):
        close = closes[i]
        prev_close = closes[i - 1]
        ma60 = ma60s[i]
        prev_ma60 = ma60s[i - 1]
        date = dates[i]

        # 賣出：收盤跌破 MA60（死亡交叉）
        if position:
            if close < ma60:
                sell_price = close
                ret_pct = (sell_price - position["buy_price"]) / position["buy_price"] * 100
                trades.append({
                    "buy_date": position["buy_date"],
                    "sell_date": date,
                    "buy_price": position["buy_price"],
                    "sell_price": sell_price,
                    "return_pct": ret_pct,
                    "hold_days": (date - position["buy_date"]).days,
                    "sell_reason": "跌破MA60",
                })
                position = None
            continue

        # 買入：收盤站上 MA60（黃金交叉）
        if not position and close > ma60 and prev_close <= prev_ma60:
            position = {"buy_date": date, "buy_price": close}

    if position:
        sell_price = closes[-1]
        ret_pct = (sell_price - position["buy_price"]) / position["buy_price"] * 100
        trades.append({
            "buy_date": position["buy_date"],
            "sell_date": dates[-1],
            "buy_price": position["buy_price"],
            "sell_price": sell_price,
            "return_pct": ret_pct,
            "hold_days": (dates[-1] - position["buy_date"]).days,
            "sell_reason": "回測結束",
        })

    return trades, closes


def print_report(trades: list[dict], df: pd.DataFrame, closes: list) -> None:
    if not trades:
        print("無交易紀錄")
        return

    # 重建 df 用於計算
    df_full = df.copy()
    df_full["MA60"] = df_full["Close"].rolling(MA_DAYS).mean()
    df_bt = df_full.dropna()
    dates = df_bt.index.tolist()
    start_price = df_bt["Close"].iloc[0]
    end_price = df_bt["Close"].iloc[-1]
    buy_hold_ret = (end_price - start_price) / start_price * 100
    total_days = len(dates)

    total_ret = 1.0
    for t in trades:
        total_ret *= 1 + t["return_pct"] / 100
    strategy_ret = (total_ret - 1) * 100
    hold_days_total = sum(t["hold_days"] for t in trades)
    years_span = total_days / 252
    strategy_cagr = (total_ret ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
    buy_hold_cagr = ((1 + buy_hold_ret / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
    time_in_market_pct = hold_days_total / total_days * 100 if total_days else 0

    print("\n" + "=" * 60)
    print(f"  MA60 趨勢跟隨策略 — {TICKER} 近{YEARS}年")
    print("=" * 60)
    print(f"  回測區間：{dates[0].date()} ~ {dates[-1].date()}")
    print(f"  交易次數：{len(trades)} 筆")
    print("-" * 60)
    print("  策略績效：")
    print(f"    累計報酬率：{strategy_ret:+.2f}%")
    print(f"    年化報酬率：{strategy_cagr:+.2f}%")
    print(f"    平均每筆報酬：{sum(t['return_pct'] for t in trades)/len(trades):+.2f}%")
    print("-" * 60)
    print("  【策略 vs 買入持有】")
    print("-" * 60)
    print(f"  {'項目':<20} {'MA60策略':>14} {'買入持有':>14}")
    print(f"  {'─'*20} {'─'*14} {'─'*14}")
    print(f"  {'累計報酬率':<20} {strategy_ret:>+13.2f}% {buy_hold_ret:>+13.2f}%")
    print(f"  {'年化報酬率':<20} {strategy_cagr:>+13.2f}% {buy_hold_cagr:>+13.2f}%")
    print(f"  {'在場時間':<20} {time_in_market_pct:>12.1f}% {'100.0':>13}%")
    print("-" * 60)
    diff = strategy_ret - buy_hold_ret
    print(f"  MA60策略 vs 買入持有：{diff:+.2f}% （{'落後' if diff < 0 else '領先'} {abs(diff):.2f}%）")
    print("-" * 60)
    for t in trades[-10:]:
        print(f"    {t['buy_date'].date()} → {t['sell_date'].date()} | {t['return_pct']:+.2f}% | {t['hold_days']}天")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    print(f"取得 {len(df)} 筆資料")
    trades, closes = run_backtest(df)
    print_report(trades, df, closes)


if __name__ == "__main__":
    main()
