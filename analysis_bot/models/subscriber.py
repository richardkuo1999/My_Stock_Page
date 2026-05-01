from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from ..utils.tz import now_tw


class Subscriber(SQLModel, table=True):
    """Telegram subscribers for auto-push notifications."""

    __table_args__ = (
        UniqueConstraint("chat_id", "topic_id", name="uq_subscriber_chat_topic"),
    )

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    topic_id: int | None = Field(default=None, index=True)  # Telegram Forum topic
    created_at: datetime = Field(default_factory=now_tw)
    news_enabled: bool = Field(default=False)  # 訂閱新聞推播
    ispike_enabled: bool = Field(default=False)  # 訂閱盤中爆量通知
    sentiment_alert_enabled: bool = Field(default=False)  # 訂閱情緒警報
    umon_enabled: bool = Field(default=False)  # 訂閱 UAnalyze 報告推播
    daily_analysis_enabled: bool = Field(default=False)  # 訂閱每日分析推播
    spike_enabled: bool = Field(default=False)  # 訂閱收盤爆量推播
    vix_enabled: bool = Field(default=False)  # 訂閱 VIX 警報推播
    wlist_enabled: bool = Field(default=False)  # 訂閱自選股同步通知
