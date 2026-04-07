from datetime import datetime

from sqlmodel import Field, SQLModel


class IntradayMA20Snapshot(SQLModel, table=True):
    """每日收盤後存入的全市場 MA20 快照，供隔日盤中爆量偵測使用。"""

    __tablename__ = "intraday_ma20_snapshot"

    ticker: str = Field(primary_key=True)
    market: str            # TWSE / TPEx
    name: str
    ma20_lots: float       # 20 日均量（張）
    snapshot_date: str     # ISO 日期字串，如 "2026-04-07"（計算當日）
    updated_at: datetime = Field(default_factory=datetime.now)
