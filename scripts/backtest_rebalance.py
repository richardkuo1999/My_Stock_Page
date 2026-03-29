#!/usr/bin/env python3
"""
樂活再平衡策略 — 高賣低買

策略：持有 0050，當偏離 TL 時再平衡
- 價格 > TL+2SD：賣出 50% 持倉（獲利了結）
- 價格 < TL-2SD：用現金加碼至滿倉

目標：高點減倉鎖利，低點加碼撿便宜。在震盪市可能優於純買入持有。

執行：python scripts/backtest_rebalance.py
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


def fetch_data(ticker: str, years: int) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=years * 365)
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, auto_adjust=True)
    if hist.empty or len(hist) < LOHAS_DAYS:
        raise ValueError("資料不足")
    return hist[["Close"]].dropna()


def compute_bands(prices: list[float]) -> dict | None:
    if len(prices) < 50:
        return None
    try:
        result = MathUtils.mean_reversion(prices)
        bands = result.get("bands", {})
        if not bands:
            return None
        return {
            "TL": bands["TL"][-1] if isinstance(bands["TL"], list) else bands["TL"],
            "TL-2SD": bands["TL-2SD"][-1] if isinstance(bands["TL-2SD"], list) else bands["TL-2SD"],
            "TL+2SD": bands["TL+2SD"][-1] if isinstance(bands["TL+2SD"], list) else bands["TL+2SD"],
        }
    except Exception:
        return None


def run_backtest(df: pd.DataFrame) -> dict:
    closes = df["Close"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    # 期初 100% 投入
    capital = 1.0
    shares = capital / closes[LOHAS_DAYS]
    cash = 0.0

    for i in range(LOHAS_DAYS, n):
        close = closes[i]
        window = closes[i - LOHAS_DAYS : i + 1]
        bands = compute_bands(window)
        if not bands:
            continue

        tl_m2 = bands["TL-2SD"]
        tl_p2 = bands["TL+2SD"]
        portfolio_value = shares * close + cash

        # 高點：賣出 50% 持倉
        if close >= tl_p2 and shares > 0:
            sell_shares = shares * 0.5
            cash += sell_shares * close
            shares -= sell_shares

        # 低點：用現金加碼至滿倉
        elif close < tl_m2 and cash > 0:
            target_value = portfolio_value  # 滿倉
            need_to_buy = target_value - shares * close
            if need_to_buy > 0 and cash > 0:
                buy_amount = min(cash, need_to_buy)
                shares += buy_amount / close
                cash -= buy_amount

    end_value = shares * closes[-1] + cash
    strategy_ret = (end_value - 1.0) / 1.0 * 100

    # 買入持有
    buy_hold_shares = 1.0 / closes[LOHAS_DAYS]
    buy_hold_end = buy_hold_shares * closes[-1]
    buy_hold_ret = (buy_hold_end - 1.0) / 1.0 * 100

    return {
        "strategy_ret": strategy_ret,
        "buy_hold_ret": buy_hold_ret,
        "total_days": n - LOHAS_DAYS,
        "dates": dates,
        "closes": closes,
    }


def print_report(result: dict) -> None:
    r = result
    total_days = r["total_days"]
    years_span = total_days / 252
    s_cagr = ((1 + r["strategy_ret"] / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
    b_cagr = ((1 + r["buy_hold_ret"] / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0

    print("\n" + "=" * 60)
    print(f"  樂活再平衡策略 — {TICKER} 近{YEARS}年")
    print("=" * 60)
    print("  高點(TL+2SD)賣50%鎖利，低點(TL-2SD)加碼滿倉")
    print("-" * 60)
    print(f"  {'策略':<25} {'累計報酬':>14} {'年化報酬':>14}")
    print(f"  {'─'*25} {'─'*14} {'─'*14}")
    print(f"  {'樂活再平衡':<25} {r['strategy_ret']:>+13.2f}% {s_cagr:>+13.2f}%")
    print(f"  {'買入持有':<25} {r['buy_hold_ret']:>+13.2f}% {b_cagr:>+13.2f}%")
    print("-" * 60)
    diff = r["strategy_ret"] - r["buy_hold_ret"]
    print(f"  樂活再平衡 vs 買入持有：{diff:+.2f}% （{'落後' if diff < 0 else '領先'} {abs(diff):.2f}%）")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    print(f"取得 {len(df)} 筆資料")
    result = run_backtest(df)
    print_report(result)


if __name__ == "__main__":
    main()
