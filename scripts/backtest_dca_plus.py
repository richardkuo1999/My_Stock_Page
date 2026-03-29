#!/usr/bin/env python3
"""
定時定額 + 低點加碼策略

策略：每月固定投入，但當股價跌破 TL-2SD 時當月加倍投入
- 正常：每月投入 1 單位
- 低點：收盤 < TL-2SD 時，當月投入 3 單位

同樣總資金下，在低點買更多，拉低平均成本。

執行：python scripts/backtest_dca_plus.py
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
NORMAL_UNITS = 1
BONUS_UNITS = 3  # 低點時投入倍數


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

    # 每月第一個交易日
    monthly_dates = []
    current_month = None
    for i, d in enumerate(dates):
        m = (d.year, d.month)
        if m != current_month:
            current_month = m
            if i >= LOHAS_DAYS:
                monthly_dates.append((i, d))

    shares = 0.0
    total_cost = 0.0
    records = []

    for idx, date in monthly_dates:
        close = closes[idx]
        window = closes[idx - LOHAS_DAYS : idx + 1]
        tl_m2 = compute_tl_m2(window)
        if tl_m2 is None:
            units = NORMAL_UNITS
        else:
            units = BONUS_UNITS if close < tl_m2 else NORMAL_UNITS

        cost = units * close
        bought = units
        total_cost += cost
        shares += bought
        records.append({
            "date": date,
            "close": close,
            "units": units,
            "cost": cost,
            "shares": shares,
            "total_cost": total_cost,
        })

    end_value = shares * closes[-1]
    total_ret = (end_value - total_cost) / total_cost * 100 if total_cost else 0

    # 對照：純定時定額（不加碼）
    shares_normal = 0.0
    cost_normal = 0.0
    for idx, _ in monthly_dates:
        close = closes[idx]
        cost_normal += NORMAL_UNITS * close
        shares_normal += NORMAL_UNITS
    end_normal = shares_normal * closes[-1]
    dca_ret = (end_normal - cost_normal) / cost_normal * 100 if cost_normal else 0

    # 買入持有：一開始用總投入買入
    lump_sum = total_cost  # 用相同總投入
    lump_shares = lump_sum / closes[LOHAS_DAYS]
    lump_end = lump_shares * closes[-1]
    buy_hold_ret = (lump_end - lump_sum) / lump_sum * 100

    return {
        "strategy_ret": total_ret,
        "dca_ret": dca_ret,
        "buy_hold_ret": buy_hold_ret,
        "total_cost": total_cost,
        "end_value": end_value,
        "shares": shares,
        "records": records,
        "dates": dates,
        "closes": closes,
    }


def print_report(result: dict) -> None:
    r = result
    dates = r["dates"]
    closes = r["closes"]
    total_days = len(dates) - LOHAS_DAYS
    years_span = total_days / 252

    print("\n" + "=" * 60)
    print(f"  定時定額 + 低點加碼 — {TICKER} 近{YEARS}年")
    print("=" * 60)
    print(f"  正常每月 1 單位，低點(TL-2SD)時 3 單位")
    print("-" * 60)
    print("  【三種策略比較】")
    print("-" * 60)
    print(f"  {'策略':<25} {'累計報酬':>14} {'年化報酬':>14}")
    print(f"  {'─'*25} {'─'*14} {'─'*14}")

    for name, ret in [
        ("定時定額+低點加碼", r["strategy_ret"]),
        ("純定時定額(對照)", r["dca_ret"]),
        ("一次買入持有(對照)", r["buy_hold_ret"]),
    ]:
        cagr = ((1 + ret / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
        print(f"  {name:<25} {ret:>+13.2f}% {cagr:>+13.2f}%")

    print("-" * 60)
    best = max(r["strategy_ret"], r["dca_ret"], r["buy_hold_ret"])
    if r["strategy_ret"] == best:
        print("  ✅ 定時定額+低點加碼 領先")
    else:
        print(f"  領先策略：{'一次買入持有' if r['buy_hold_ret']==best else '純定時定額'}")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    print(f"取得 {len(df)} 筆資料")
    result = run_backtest(df)
    print_report(result)


if __name__ == "__main__":
    main()
