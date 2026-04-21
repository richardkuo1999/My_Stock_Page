from datetime import datetime

from sqlmodel import Field, SQLModel


class UmonTarget(SQLModel, table=True):
    """UAnalyze monitor push target (chat_id + optional topic_id)."""

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    topic_id: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now)
