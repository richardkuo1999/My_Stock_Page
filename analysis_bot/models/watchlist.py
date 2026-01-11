from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class WatchlistItem(SQLModel, table=True):
    """Per-chat watchlist tickers for Telegram bot."""

    __table_args__ = (UniqueConstraint("chat_id", "ticker", name="uq_watchlist_chat_ticker"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    ticker: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

