#!/usr/bin/env python3
"""
樂活五線譜均值回歸回測 — 0050 十年回測

策略：
- 買入：收盤價跌破 TL-2SD（極悲觀價位）
- 賣出：收盤價回到 TL+2SD（極樂觀價位）

執行：python scripts/backtest_lohas.py
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
LOHAS_DAYS = int(3.5 * 252)  # 3.5 年約 880 個交易日


def fetch_data(ticker: str, years: int) -> pd.DataFrame:
    """取得歷史收盤價"""
    end = datetime.now()
    start = end - timedelta(days=years * 365)
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, auto_adjust=True)
    if hist.empty or len(hist) < LOHAS_DAYS:
        raise ValueError(f"資料不足：需要至少 {LOHAS_DAYS} 筆，取得 {len(hist)} 筆")
    return hist[["Close"]].dropna()


def compute_bands_at(prices: list[float]) -> dict | None:
    """計算 TL、TL-2SD、TL+1SD 的最後一個值（當日）"""
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


def run_backtest(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """執行回測，回傳交易紀錄與每日持倉"""
    closes = df["Close"].tolist()
    dates = df.index.tolist()
    n = len(closes)

    trades: list[dict] = []
    position: dict | None = None  # {"buy_date", "buy_price", "buy_idx", "shares"}

    for i in range(LOHAS_DAYS, n):
        window = closes[i - LOHAS_DAYS : i + 1]
        bands = compute_bands_at(window)
        if not bands:
            continue

        close = closes[i]
        date = dates[i]
        tl = bands["TL"]
        tl_m2 = bands["TL-2SD"]
        tl_p2 = bands["TL+2SD"]

        # 賣出邏輯（若持倉中）
        if position:
            hold_days = i - position["buy_idx"]
            if close >= tl_p2:
                sell_price = close
                ret_pct = (sell_price - position["buy_price"]) / position["buy_price"] * 100
                trades.append({
                    "buy_date": position["buy_date"],
                    "sell_date": date,
                    "buy_price": position["buy_price"],
                    "sell_price": sell_price,
                    "return_pct": ret_pct,
                    "hold_days": hold_days,
                    "sell_reason": "回到TL+2SD",
                })
                position = None
                continue

        # 買入邏輯（若未持倉）
        if not position and close < tl_m2:
            position = {
                "buy_date": date,
                "buy_price": close,
                "buy_idx": i,
                "shares": 1,
            }

    # 若回測結束仍持倉，以最後收盤價結算
    if position:
        sell_price = closes[-1]
        ret_pct = (sell_price - position["buy_price"]) / position["buy_price"] * 100
        trades.append({
            "buy_date": position["buy_date"],
            "sell_date": dates[-1],
            "buy_price": position["buy_price"],
            "sell_price": sell_price,
            "return_pct": ret_pct,
            "hold_days": n - 1 - position["buy_idx"],
            "sell_reason": "回測結束",
        })

    return trades, closes


def print_report(trades: list[dict], df: pd.DataFrame) -> None:
    """輸出回測報告"""
    if not trades:
        print("無交易紀錄")
        return

    closes = df["Close"].tolist()
    dates = df.index.tolist()
    start_price = closes[LOHAS_DAYS]
    end_price = closes[-1]
    buy_hold_ret = (end_price - start_price) / start_price * 100

    wins = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]

    print("\n" + "=" * 60)
    print(f"  樂活五線譜回測 — {TICKER} 近{YEARS}年")
    print("=" * 60)
    print(f"  回測區間：{dates[LOHAS_DAYS].date()} ~ {dates[-1].date()}")
    print(f"  交易次數：{len(trades)} 筆")
    print("-" * 60)
    print("  策略績效：")
    total_ret = 1.0
    for t in trades:
        total_ret *= 1 + t["return_pct"] / 100
    strategy_ret = (total_ret - 1) * 100
    print(f"    累計報酬率：{strategy_ret:+.2f}%")
    print(f"    勝率：{len(wins)}/{len(trades)} = {len(wins)/len(trades)*100:.1f}%")
    print(f"    平均每筆報酬：{sum(t['return_pct'] for t in trades)/len(trades):+.2f}%")
    print(f"    平均持有天數：{sum(t['hold_days'] for t in trades)/len(trades):.1f} 天")
    if wins:
        print(f"    平均獲利：{sum(t['return_pct'] for t in wins)/len(wins):+.2f}%")
    if losses:
        print(f"    平均虧損：{sum(t['return_pct'] for t in losses)/len(losses):+.2f}%")
    # 策略 vs 買入持有 比較
    total_days = len(dates) - LOHAS_DAYS
    hold_days_total = sum(t["hold_days"] for t in trades)
    time_in_market_pct = hold_days_total / total_days * 100 if total_days else 0

    years_span = total_days / 252
    strategy_cagr = (total_ret ** (1 / years_span) - 1) * 100 if years_span > 0 else 0
    buy_hold_cagr = ((1 + buy_hold_ret / 100) ** (1 / years_span) - 1) * 100 if years_span > 0 else 0

    print("-" * 60)
    print("  【策略 vs 買入持有 比較】")
    print("-" * 60)
    print(f"  {'項目':<20} {'樂活策略':>14} {'買入持有':>14}")
    print(f"  {'─'*20} {'─'*14} {'─'*14}")
    print(f"  {'累計報酬率':<20} {strategy_ret:>+13.2f}% {buy_hold_ret:>+13.2f}%")
    print(f"  {'年化報酬率 (CAGR)':<20} {strategy_cagr:>+13.2f}% {buy_hold_cagr:>+13.2f}%")
    print(f"  {'持有天數':<20} {hold_days_total:>13}天 {total_days:>13}天")
    print(f"  {'在場時間比例':<20} {time_in_market_pct:>12.1f}% {'100.0':>13}%")
    print("-" * 60)
    diff = strategy_ret - buy_hold_ret
    print(f"  樂活策略 vs 買入持有：{diff:+.2f}% （{'落後' if diff < 0 else '領先'} {abs(diff):.2f}%）")
    print("-" * 60)
    print("  交易明細（最近 10 筆）：")
    for t in trades[-10:]:
        print(f"    {t['buy_date'].date()} → {t['sell_date'].date()} | "
              f"{t['return_pct']:+.2f}% | {t['hold_days']}天 | {t['sell_reason']}")
    print("=" * 60 + "\n")


def main():
    print(f"正在取得 {TICKER} 近{YEARS}年資料...")
    df = fetch_data(TICKER, YEARS)
    print(f"取得 {len(df)} 筆交易日資料")

    print("執行回測...")
    trades, _ = run_backtest(df)
    print_report(trades, df)


if __name__ == "__main__":
    main()
