from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class WatchlistEntry(SQLModel, table=True):
    """Per-chat, per-user watchlist entries for Telegram bot."""

    __tablename__ = "watchlist_entry"

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "ticker", name="uq_watchlist_chat_user_ticker"),
    )

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    user_id: int = Field(index=True)
    ticker: str = Field(index=True)
    alias: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
