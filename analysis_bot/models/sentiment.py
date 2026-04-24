"""新聞情緒分析資料模型。"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.tz import now_tw


class NewsSentiment(SQLModel, table=True):
    """News sentiment analysis results."""

    __tablename__ = "news_sentiment"

    id: int | None = Field(default=None, primary_key=True)
    news_id: int = Field(index=True, foreign_key="news.id")
    ticker: str | None = Field(default=None, index=True)  # 相關股票代碼
    sentiment: str = Field(default="neutral")  # positive / neutral / negative
    score: float = Field(default=0.0)  # -1.0 ~ 1.0
    created_at: datetime = Field(default_factory=now_tw)
