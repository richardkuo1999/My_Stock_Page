from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from ..utils.tz import now_tw


class IntradayMA20Snapshot(SQLModel, table=True):
    """
    全市場盤中爆量偵測快照。

    兩種更新路徑：
    - 08:00 盤前排程：寫入 vol_19d_sum_lots（過去 19 日成交量加總，張）
    - 15:30 收盤排程：寫入 ma20_lots（舊版 20 日均量，向後相容保留）
    """

    __tablename__ = "intraday_ma20_snapshot"

    ticker: str = Field(primary_key=True)
    market: str                          # TWSE / TPEx
    name: str
    ma20_lots: float = 0.0              # 舊版：20 日均量（張），收盤掃描寫入
    vol_19d_sum_lots: Optional[float] = Field(default=None)  # 盤前掃描：過去 19 日量加總（張）
    snapshot_date: str = ""             # ISO 日期字串，如 "2026-04-07"
    updated_at: datetime = Field(default_factory=now_tw)
