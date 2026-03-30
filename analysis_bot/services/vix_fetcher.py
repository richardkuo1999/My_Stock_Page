"""
VIX Fetcher — 抓取 VIX 恐慌指數並產生警報訊息

統計基準（1990-2026，9126 天）：
  平均值：19.46  標準差：7.77
  +1SD：27.23   +2SD：35.00   +3SD：42.76
  單日漲跌 1SD：7.13%   2SD：14.27%
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 歷史統計基準 ──────────────────────────────────────────────
VIX_MEAN = 19.46
VIX_STD = 7.77
VIX_DAILY_PCT_STD = 7.13  # 單日漲跌標準差 %

VIX_WARN = VIX_MEAN + 1 * VIX_STD  # 27.23 — 注意
VIX_FEAR = VIX_MEAN + 2 * VIX_STD  # 35.00 — 恐慌
VIX_EXTREME = VIX_MEAN + 3 * VIX_STD  # 42.76 — 極端事件
VIX_CALM = VIX_MEAN - 1 * VIX_STD  # 11.69 — 過度樂觀

DAILY_SPIKE_UP_THRESHOLD = 2 * VIX_DAILY_PCT_STD  # 14.27% — 急漲警報（只偵測上漲）

# 敘述門檻（與 μ/σ 分類獨立，對應常見市場解讀）
VIX_NARRATIVE_HIGH = 30.0
VIX_NARRATIVE_VERY_HIGH = 35.0
VIX_NARRATIVE_EXTREME = 40.0


def _narrative_block(vix: float) -> list[str]:
    """依 VIX 數值回傳歷史情境與統計敘述（由高到低只取一層）。"""
    if vix > VIX_NARRATIVE_EXTREME:
        return [
            "📌 VIX > 40｜系統性風險、黑天鵝事件",
            "　情境：歷史上僅在少數極端事件出現（如 2008 金融海嘯、2011 美債降評、"
            "2015 人民幣重貶、2020 新冠疫情）。",
            "　持有 1 年勝率（歷史參考）：逼近 100%。",
            "　平均預期報酬（歷史參考）：1 年後常突破 25% 甚至更高；此環境常接近歷史級相對底部區。",
        ]
    if vix > VIX_NARRATIVE_VERY_HIGH:
        return [
            "📌 VIX > 35｜非理性拋售、恐慌蔓延",
            "　情境：較大利空、多殺多與融資斷頭潮。",
            "　持有 1 年勝率（歷史參考）：約 90% 以上。",
            "　平均預期報酬（歷史參考）：1 年後約 15%–20%；相對罕見恐慌極值，長線勝率極高。",
        ]
    if vix > VIX_NARRATIVE_HIGH:
        return [
            "📌 VIX > 30｜嚴重恐慌與修正",
            "　情境：常伴隨大盤自高點回檔約 10%–15% 的中段修正。",
            "　持有 1 年勝率（歷史參考）：約 80%–85%。",
            "　平均預期報酬（歷史參考）：1 年後約 10%–15%；長線買點訊號浮現，短線仍可能劇烈震盪。",
        ]
    return []


@dataclass
class VixSnapshot:
    current: float
    prev_close: float
    daily_change_pct: float
    level: str  # "calm" | "normal" | "warn" | "fear" | "extreme"
    alert: bool  # 需要推播


def _classify(vix: float) -> str:
    if vix >= VIX_EXTREME:
        return "extreme"
    if vix >= VIX_FEAR:
        return "fear"
    if vix >= VIX_WARN:
        return "warn"
    if vix <= VIX_CALM:
        return "calm"
    return "normal"


async def fetch_vix_snapshot() -> VixSnapshot | None:
    """抓取 VIX 最新值與昨日收盤，計算漲跌幅。"""
    try:
        import yfinance as yf

        data = await asyncio.to_thread(
            lambda: yf.download("^VIX", period="5d", progress=False)["Close"].squeeze()
        )
        if data is None or len(data) < 2:
            logger.warning("VIX data insufficient")
            return None

        current = float(data.iloc[-1])
        prev = float(data.iloc[-2])

        # #1 除零保護
        if prev <= 0:
            logger.warning(f"VIX prev_close is invalid: {prev}")
            return None

        pct = (current - prev) / prev * 100

        level = _classify(current)
        # #8 只偵測急漲（VIX 急跌不代表危險）
        alert = current >= VIX_WARN or pct >= DAILY_SPIKE_UP_THRESHOLD

        return VixSnapshot(
            current=current,
            prev_close=prev,
            daily_change_pct=pct,
            level=level,
            alert=alert,
        )
    except Exception as e:
        logger.error(f"VIX fetch failed: {e}")
        return None


def format_vix_message(snap: VixSnapshot) -> str:
    """產生 Telegram 推播訊息。"""
    level_emoji = {
        "calm": "🟢",
        "normal": "🔵",
        "warn": "🟡",
        "fear": "🔴",
        "extreme": "🚨",
    }
    level_label = {
        "calm": "過度樂觀（<+1SD，需警戒）",
        "normal": "正常",
        "warn": "偏高（>+1SD）",
        "fear": "恐慌（>+2SD）",
        "extreme": "極端事件（>+3SD）",
    }

    emoji = level_emoji.get(snap.level, "❓")
    sign = "+" if snap.daily_change_pct >= 0 else ""

    lines = [
        f"{emoji} VIX 恐慌指數",
        f"現值：{snap.current:.2f}　昨收：{snap.prev_close:.2f}",
        f"日變動：{sign}{snap.daily_change_pct:.1f}%",
        f"狀態：{level_label.get(snap.level, snap.level)}",
        "",
        f"參考：⚠️ {VIX_WARN:.0f}　🔴 {VIX_FEAR:.0f}　🚨 {VIX_EXTREME:.0f}",
    ]

    if snap.daily_change_pct >= DAILY_SPIKE_UP_THRESHOLD:
        lines.append(f"⚡ 單日急漲超過 2SD（{DAILY_SPIKE_UP_THRESHOLD:.0f}%）")

    narrative = _narrative_block(snap.current)
    if narrative:
        lines.extend(
            [
                "",
                *narrative,
                "",
                "（上述勝率／報酬為歷史區間統計，不構成投資建議，亦不保證未來表現。）",
            ]
        )

    return "\n".join(lines)
