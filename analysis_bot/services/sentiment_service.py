"""新聞情緒分析服務。

使用 AI (Gemini) 對新聞標題進行情緒分類，
並提供個股情緒趨勢查詢與急轉通知功能。
"""

import json
import logging
from datetime import timedelta

from sqlmodel import Session, select

from ..database import engine
from ..models.sentiment import NewsSentiment
from ..utils.tz import now_tw

logger = logging.getLogger(__name__)


class SentimentService:
    """新聞情緒分析服務。"""

    SENTIMENT_PROMPT = """你是一位專業的財經新聞情緒分析師。
請分析以下新聞標題的情緒傾向，判斷對相關股票/市場的影響。

規則：
1. 回傳 JSON 格式：{{"sentiment": "positive|neutral|negative", "score": 0.0, "tickers": []}}
2. score 範圍 -1.0（極度負面）到 1.0（極度正面）
3. tickers 列出新聞中提到的台股代碼（4-5位數字），沒有就留空陣列
4. 只回傳 JSON，不要其他文字

新聞標題列表（每行一則）：
{titles}
"""

    BATCH_PROMPT = """你是一位專業的財經新聞情緒分析師。
請分析以下新聞標題的情緒傾向。

規則：
1. 回傳 JSON 陣列，每個元素對應一則新聞
2. 格式：[{{"sentiment": "positive|neutral|negative", "score": 0.0, "tickers": []}}]
3. score 範圍 -1.0（極度負面）到 1.0（極度正面）
4. tickers 列出新聞中提到的台股代碼（4-5位數字），沒有就留空陣列
5. 只回傳 JSON 陣列，不要其他文字
6. 陣列長度必須等於新聞數量

新聞標題列表：
{titles}
"""

    @staticmethod
    async def analyze_batch(titles: list[str], ai_service=None) -> list[dict]:
        """批次分析多則新聞標題的情緒。

        Returns:
            list of {"sentiment": str, "score": float, "tickers": list[str]}
        """
        if not titles:
            return []

        if ai_service is None:
            from .ai_service import AIService
            ai_service = AIService()

        # 每批最多 20 則避免 token 過長
        batch_size = 20
        all_results = []

        for i in range(0, len(titles), batch_size):
            batch = titles[i:i + batch_size]
            numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(batch))
            prompt = SentimentService.BATCH_PROMPT.format(titles=numbered)

            try:
                from .ai_service import RequestType
                response = await ai_service.call(RequestType.TEXT, contents=prompt)
                parsed = _parse_sentiment_response(response, len(batch))
                all_results.extend(parsed)
            except Exception as e:
                logger.warning("Sentiment batch analysis failed: %s", e)
                # Fallback: 全部標記為 neutral
                all_results.extend(
                    [{"sentiment": "neutral", "score": 0.0, "tickers": []}] * len(batch)
                )

        return all_results

    @staticmethod
    def save_sentiments(
        news_ids: list[int], sentiments: list[dict]
    ) -> list[NewsSentiment]:
        """將情緒分析結果存入資料庫。

        news_ids: list of News.id
        sentiments: list of {"sentiment": str, "score": float, "tickers": list[str]}
        """
        records = []
        with Session(engine) as session:
            for nid, sent in zip(news_ids, sentiments):
                tickers = sent.get("tickers", [])
                ticker_list = tickers if tickers else [None]
                for ticker in ticker_list:
                    record = NewsSentiment(
                        news_id=nid,
                        ticker=ticker,
                        sentiment=sent.get("sentiment", "neutral"),
                        score=sent.get("score", 0.0),
                    )
                    session.add(record)
                    records.append(record)
            session.commit()
        return records

    @staticmethod
    def get_ticker_sentiment_trend(ticker: str, days: int = 7) -> dict:
        """取得個股近 N 天的情緒趨勢。

        Returns:
            {
                "ticker": str,
                "total": int,
                "positive": int,
                "neutral": int,
                "negative": int,
                "avg_score": float,
                "daily": [{"date": str, "positive": int, "neutral": int, "negative": int, "avg": float}]
            }
        """
        cutoff = now_tw() - timedelta(days=days)
        with Session(engine) as session:
            records = session.exec(
                select(NewsSentiment)
                .where(NewsSentiment.ticker == ticker)
                .where(NewsSentiment.created_at >= cutoff)
                .order_by(NewsSentiment.created_at.desc())
            ).all()

        if not records:
            return {
                "ticker": ticker,
                "total": 0,
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "avg_score": 0.0,
                "daily": [],
            }

        positive = sum(1 for r in records if r.sentiment == "positive")
        neutral = sum(1 for r in records if r.sentiment == "neutral")
        negative = sum(1 for r in records if r.sentiment == "negative")
        avg_score = sum(r.score for r in records) / len(records)

        # 按日分組
        daily_map: dict[str, list[NewsSentiment]] = {}
        for r in records:
            day_key = r.created_at.strftime("%m/%d")
            daily_map.setdefault(day_key, []).append(r)

        daily = []
        for day_key, day_records in sorted(daily_map.items()):
            daily.append({
                "date": day_key,
                "positive": sum(1 for r in day_records if r.sentiment == "positive"),
                "neutral": sum(1 for r in day_records if r.sentiment == "neutral"),
                "negative": sum(1 for r in day_records if r.sentiment == "negative"),
                "avg": sum(r.score for r in day_records) / len(day_records),
            })

        return {
            "ticker": ticker,
            "total": len(records),
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "avg_score": round(avg_score, 3),
            "daily": daily,
        }

    @staticmethod
    def check_sentiment_shift(ticker: str, threshold: int = 3) -> str | None:
        """檢查個股是否出現情緒急轉（連續 N 則負面新聞）。

        Returns:
            警告訊息字串，或 None（無急轉）
        """
        from ..models.content import News

        with Session(engine) as session:
            recent = session.exec(
                select(NewsSentiment, News.title)
                .join(News, NewsSentiment.news_id == News.id)
                .where(NewsSentiment.ticker == ticker)
                .order_by(NewsSentiment.created_at.desc())
                .limit(threshold)
            ).all()

        if len(recent) < threshold:
            return None

        if all(r[0].sentiment == "negative" for r in recent):
            titles = "\n".join(f"• {r[1][:60]}" for r in recent[:3])
            return (
                f"⚠️ {ticker} 情緒急轉警報\n"
                f"連續 {threshold} 則負面新聞：\n{titles}"
            )
        return None

    @staticmethod
    def get_market_sentiment_summary() -> dict:
        """取得整體市場情緒摘要（近 24 小時）。"""
        cutoff = now_tw() - timedelta(hours=24)
        with Session(engine) as session:
            records = session.exec(
                select(NewsSentiment)
                .where(NewsSentiment.created_at >= cutoff)
            ).all()

        if not records:
            return {"total": 0, "positive": 0, "neutral": 0, "negative": 0, "avg_score": 0.0}

        return {
            "total": len(records),
            "positive": sum(1 for r in records if r.sentiment == "positive"),
            "neutral": sum(1 for r in records if r.sentiment == "neutral"),
            "negative": sum(1 for r in records if r.sentiment == "negative"),
            "avg_score": round(sum(r.score for r in records) / len(records), 3),
        }

    @staticmethod
    def check_market_sentiment_shift(hours: int = 24) -> str | None:
        """比較前後時段的市場情緒，偵測正轉負或負轉正。

        比較「近 N 小時」vs「前 N~2N 小時」的平均分數，
        若跨越 0 分界線則回傳通知訊息。
        """
        now = now_tw()
        current_start = now - timedelta(hours=hours)
        previous_start = now - timedelta(hours=hours * 2)

        with Session(engine) as session:
            current_records = session.exec(
                select(NewsSentiment).where(
                    NewsSentiment.created_at >= current_start
                )
            ).all()
            previous_records = session.exec(
                select(NewsSentiment).where(
                    NewsSentiment.created_at >= previous_start,
                    NewsSentiment.created_at < current_start,
                )
            ).all()

        if not current_records or not previous_records:
            return None

        curr_avg = sum(r.score for r in current_records) / len(current_records)
        prev_avg = sum(r.score for r in previous_records) / len(previous_records)

        if prev_avg >= 0 and curr_avg < 0:
            return (
                f"🔴 市場情緒轉變警報：正面 → 負面\n"
                f"前期平均：{prev_avg:+.3f}（{len(previous_records)} 則）\n"
                f"近期平均：{curr_avg:+.3f}（{len(current_records)} 則）"
            )
        elif prev_avg <= 0 and curr_avg > 0:
            return (
                f"🟢 市場情緒轉變通知：負面 → 正面\n"
                f"前期平均：{prev_avg:+.3f}（{len(previous_records)} 則）\n"
                f"近期平均：{curr_avg:+.3f}（{len(current_records)} 則）"
            )
        return None


def _parse_sentiment_response(response: str, expected_count: int) -> list[dict]:
    """解析 AI 回傳的情緒分析 JSON。"""
    default = {"sentiment": "neutral", "score": 0.0, "tickers": []}

    if not response:
        return [default.copy() for _ in range(expected_count)]

    # 嘗試提取 JSON
    text = response.strip()
    # 移除 markdown code block
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
        if isinstance(data, list):
            results = []
            for item in data:
                results.append({
                    "sentiment": item.get("sentiment", "neutral"),
                    "score": float(item.get("score", 0.0)),
                    "tickers": item.get("tickers", []),
                })
            # 補齊不足的
            while len(results) < expected_count:
                results.append(default.copy())
            return results[:expected_count]
        elif isinstance(data, dict):
            # 單則結果
            result = {
                "sentiment": data.get("sentiment", "neutral"),
                "score": float(data.get("score", 0.0)),
                "tickers": data.get("tickers", []),
            }
            return [result] + [default.copy() for _ in range(expected_count - 1)]
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug("Failed to parse sentiment JSON: %s", e)

    return [default.copy() for _ in range(expected_count)]
