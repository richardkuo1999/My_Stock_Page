"""此聊天室要監控的 Threads 使用者（不含 @）與已見過的貼文 id（JSON 陣列字串）。"""

from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class ThreadsWatchEntry(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("chat_id", "topic_id", "threads_username", name="uq_threads_watch_chat_topic_user"),
    )

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True, description="Telegram chat_id")
    topic_id: Optional[int] = Field(default=None, index=True, description="Telegram Forum topic")
    threads_username: str = Field(index=True, description="Threads 帳號，不含 @")
    seen_post_ids: str = Field(default="[]", description="JSON 陣列：已見過的 post id")
