#!/usr/bin/env python3
"""
低點融資加碼策略

策略：買入持有為主，低點時融資加碼
- 期初：100% 投入
- 跌破 TL-2SD：融資加碼 50%（總持股 150%）
- 漲回 TL：賣出加碼部分還款（回到 100%）

在低點有更多持股，參與反彈。需承擔融資成本與波動風險。

執行：python scripts/backtest_leverage_dip.py
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
LEVERAGE_RATIO = 0.5  # 低點時加碼 50%


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


def compute_tl(prices: list[float]) -> float | None:
    if len(prices) < 50:
        return None
    try:
        result = MathUtils.mean_reversion(prices)
        bands = result.get("bands", {})
        v = bands.get("TL")
        return v[-1] if isinstance(v, list) else v
    except Exception:
        return None


def run_backtest(df: pd.DataFrame) -> dict:
    closes = df["Close"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    base_shares = 1.0 / closes[LOHAS_DAYS]
    bonus_shares = 0.0
    cash = 0.0
    in_bonus = False

    for i in range(LOHAS_DAYS, n):
        close = closes[i]
        window = closes[i - LOHAS_DAYS : i + 1]
        tl_m2 = compute_tl_m2(window)
        tl = compute_tl(window)
        if tl_m2 is None or tl is None:
            continue

        # 跌破 TL-2SD：融資加碼
        if close < tl_m2 and not in_bonus:
            portfolio_val = (base_shares + bonus_shares) * close + cash
            add_val = portfolio_val * LEVERAGE_RATIO
            bonus_shares += add_val / close
            in_bonus = True

        # 漲回 TL：賣出加碼部分，鎖定利潤
        elif close >= tl and in_bonus:
            cash += bonus_shares * close
            bonus_shares = 0.0
            in_bonus = False

    end_value = (base_shares + bonus_shares) * closes[-1] + cash
    strategy_ret = (end_value - 1.0) / 1.0 * 100

    buy_hold_shares = 1.0 / closes[LOHAS_DAYS]
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
    print(f"  低點融資加碼策略 — {TICKER} 近{YEARS}年")
    print("=" * 60)
    print(f"  低點(TL-2SD)加碼{LEVERAGE_RATIO*100:.0f}%，漲回TL還款")
    print("-" * 60)
    print(f"  {'策略':<25} {'累計報酬':>14} {'年化報酬':>14}")
    print(f"  {'─'*25} {'─'*14} {'─'*14}")
    print(f"  {'低點融資加碼':<25} {r['strategy_ret']:>+13.2f}% {s_cagr:>+13.2f}%")
    print(f"  {'買入持有':<25} {r['buy_hold_ret']:>+13.2f}% {b_cagr:>+13.2f}%")
    print("-" * 60)
    diff = r["strategy_ret"] - r["buy_hold_ret"]
    status = "領先" if diff > 0 else "落後"
    print(f"  融資加碼 vs 買入持有：{diff:+.2f}% （{status} {abs(diff):.2f}%）")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    result = run_backtest(df)
    print_report(result)


if __name__ == "__main__":
    main()
