from datetime import datetime

from sqlmodel import Field, SQLModel


class Subscriber(SQLModel, table=True):
    """Telegram subscribers for auto-push notifications."""

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)
