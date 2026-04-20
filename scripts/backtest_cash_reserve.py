#!/usr/bin/env python3
"""
保留現金 + 低點加碼策略（無槓桿）

策略：期初保留部分現金，等低點加碼，加碼後不賣、持有到結束
- 期初：80% 持股，20% 現金（保留火力）
- 跌破 TL-2SD：用現金加碼，加碼後持有至回測結束

完全使用自有資金，不融資。若低點出現，20% 買得比期初便宜。

執行：python scripts/backtest_cash_reserve.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from analysis_bot.services.math_utils import MathUtils

TICKER = "0050.TW"
YEARS = 10
LOHAS_DAYS = int(3.5 * 252)
INITIAL_STOCK_PCT = 0.8  # 期初 80% 持股，20% 現金


def fetch_data(ticker: str, years: int) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=years * 365)
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, auto_adjust=True)
    if hist.empty or len(hist) < LOHAS_DAYS:
        raise ValueError("資料不足")
    return hist[["Close"]].dropna()


def compute_tl_m2(prices: list[float]) -> float | None:
    if len(prices) < 50:
        return None
    try:
        result = MathUtils.mean_reversion(prices)
        bands = result.get("bands", {})
        v = bands.get("TL-2SD")
        return v[-1] if isinstance(v, list) else v
    except Exception:
        return None


def run_backtest(df: pd.DataFrame) -> dict:
    closes = df["Close"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    # 期初：80% 買入，20% 現金
    initial_price = closes[LOHAS_DAYS]
    shares = INITIAL_STOCK_PCT / initial_price
    cash = 1.0 - INITIAL_STOCK_PCT
    added_once = False

    for i in range(LOHAS_DAYS, n):
        close = closes[i]
        window = closes[i - LOHAS_DAYS : i + 1]
        tl_m2 = compute_tl_m2(window)
        if tl_m2 is None:
            continue

        # 跌破 TL-2SD：用全部現金加碼（只加碼一次，加碼後持有至結束）
        if close < tl_m2 and cash > 0.001 and not added_once:
            shares += cash / close
            cash = 0.0
            added_once = True

    end_value = shares * closes[-1] + cash
    strategy_ret = (end_value - 1.0) / 1.0 * 100

    buy_hold_shares = 1.0 / initial_price
    buy_hold_end = buy_hold_shares * closes[-1]
    buy_hold_ret = (buy_hold_end - 1.0) / 1.0 * 100

    return {
        "strategy_ret": strategy_ret,
        "buy_hold_ret": buy_hold_ret,
        "total_days": n - LOHAS_DAYS,
    }


def print_report(result: dict) -> None:
    r = result
    total_days = r["total_days"]
    years_span = total_days / 252
    s_cagr = ((1 + r["strategy_ret"] / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
    b_cagr = ((1 + r["buy_hold_ret"] / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0

    print("\n" + "=" * 60)
    print(f"  保留現金 + 低點加碼（無槓桿）— {TICKER} 近{YEARS}年")
    print("=" * 60)
    print(f"  期初 {INITIAL_STOCK_PCT*100:.0f}% 持股、{100-INITIAL_STOCK_PCT*100:.0f}% 現金")
    print("  跌破 TL-2SD 用現金加碼，加碼後持有至結束")
    print("-" * 60)
    print(f"  {'策略':<25} {'累計報酬':>14} {'年化報酬':>14}")
    print(f"  {'─'*25} {'─'*14} {'─'*14}")
    print(f"  {'保留現金+低點加碼':<25} {r['strategy_ret']:>+13.2f}% {s_cagr:>+13.2f}%")
    print(f"  {'買入持有':<25} {r['buy_hold_ret']:>+13.2f}% {b_cagr:>+13.2f}%")
    print("-" * 60)
    diff = r["strategy_ret"] - r["buy_hold_ret"]
    status = "領先" if diff > 0 else "落後"
    print(f"  策略 vs 買入持有：{diff:+.2f}% （{status} {abs(diff):.2f}%）")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    result = run_backtest(df)
    print_report(result)


if __name__ == "__main__":
    main()
