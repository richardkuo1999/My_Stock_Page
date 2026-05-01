from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ..utils.tz import now_tw


class GSheetSubscription(SQLModel, table=True):
    """用戶註冊的 Google Sheets URL，用於定時同步自選股。"""

    __tablename__ = "gsheet_subscription"

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "url", name="uq_gsheet_sub_chat_user_url"),
    )

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    user_id: int = Field(index=True)
    url: str  # Google Sheets URL (含 gid)
    label: str | None = Field(default=None)  # 用戶自訂標籤（例如「短線持股」）
    user_name: str | None = Field(default=None)  # Telegram 顯示名稱
    last_hash: str | None = Field(default=None)  # 上次內容 hash，用於偵測變更
    synced_at: datetime | None = Field(default=None)  # 最後成功同步時間
    created_at: datetime = Field(default_factory=now_tw)
