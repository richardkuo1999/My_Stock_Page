"""draw_kchart — 繪製 K 線圖並回傳圖片路徑
用法: python tools/analysis/draw_kchart.py SYMBOL [--period N]
回傳: JSON {"image_path": "<系統暫存目錄>/kchart_SYMBOL_*.png"}
"""

import asyncio
import json
import logging
import os
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import mplfinance as mpf
import pandas as pd
from dotenv import load_dotenv

# 直接跑時補 repo 根到 sys.path，以便 import tools.raw.fugle。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.raw import fugle as raw_fugle
from tools.analysis._chart_font import setup_cjk_font

# 選中的跨平台中文字型（同時設全域 rcParams）；mplfinance 會用自己的 style rcParams
# 覆蓋全域，故 _render_chart 需再把此字型透過 make_mpf_style(rc=...) 傳進去。
_CJK_FONT = setup_cjk_font()

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_PERIOD = 60
MA_PERIODS = [5, 20, 60]


async def _fetch_historical(symbol: str, period: int) -> pd.DataFrame | None:
    """歷史日K（委派 raw/fugle），整成 mplfinance 要的 OHLCV frame（analysis 加工）。"""
    # 多取 MA60 + 假日緩衝，讓 MA 從第一天就畫得出來。
    extra_days = max(MA_PERIODS) + 30
    res = await raw_fugle.fetch_historical_candles(symbol, days=period + extra_days)
    if not isinstance(res, dict) or "error" in res:
        return None
    candles = res.get("data", [])
    if not candles:
        return None

    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df.sort_index(inplace=True)
    return df


def _render_chart(df: pd.DataFrame, symbol: str, period: int) -> str:
    """Render K-line chart with mplfinance and save as PNG."""
    # Take only the requested period for display
    display_df = df.tail(period)

    if len(display_df) < 5:
        raise ValueError(f"資料不足，僅有 {len(display_df)} 筆")

    # mplfinance style - Taiwan style (red=up, green=down)
    mc = mpf.make_marketcolors(
        up="#e74c3c", down="#2ecc71",
        edge={"up": "#e74c3c", "down": "#2ecc71"},
        wick={"up": "#e74c3c", "down": "#2ecc71"},
        volume={"up": "#e74c3c", "down": "#2ecc71"},
    )
    # mplfinance 會用 style 內的 rcParams 覆蓋全域，故把中文字型透過 rc 傳進去，
    # 否則標題/軸的中文（如「日K」）會變方框。
    rc = {}
    if _CJK_FONT:
        rc = {"font.sans-serif": [_CJK_FONT], "axes.unicode_minus": False}
    style = mpf.make_mpf_style(
        marketcolors=mc, gridstyle="-", gridcolor="#f0f0f0", rc=rc
    )

    # Create temp file
    fd, path = tempfile.mkstemp(prefix=f"kchart_{symbol}_", suffix=".png")
    os.close(fd)

    # Plot
    mpf.plot(
        display_df,
        type="candle",
        style=style,
        mav=tuple(MA_PERIODS),
        volume=True,
        title=f"{symbol} 日K ({len(display_df)}日)",
        figsize=(12, 6),
        savefig=dict(fname=path, dpi=100, bbox_inches="tight"),
    )

    return path


async def draw(symbol: str, period: int = DEFAULT_PERIOD) -> dict:
    """Draw K-line chart for a stock.

    Args:
        symbol: Taiwan stock symbol, e.g. '2330'
        period: Number of trading days to display

    Returns:
        dict with 'image_path' key on success, or 'error' key on failure
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "請輸入股票代號"}

    df = await _fetch_historical(symbol, period)
    if df is None or df.empty:
        return {"error": f"找不到股票代號 {symbol} 的歷史資料"}

    try:
        # matplotlib 繪圖是同步 CPU 工作，offload 到 thread 避免卡住事件迴圈
        path = await asyncio.to_thread(_render_chart, df, symbol, period)
        return {"image_path": path}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("Chart render error for %s: %s", symbol, e)
        return {"error": f"繪圖失敗: {e}"}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "用法: python tools/analysis/draw_kchart.py SYMBOL [--period N]"}, ensure_ascii=False))
        sys.exit(1)

    symbol = args[0]
    period = DEFAULT_PERIOD
    if "--period" in args:
        try:
            period = int(args[args.index("--period") + 1])
        except (IndexError, ValueError):
            pass

    result = asyncio.run(draw(symbol, period))
    print(json.dumps(result, ensure_ascii=False))
    if "error" in result:
        sys.exit(1)
