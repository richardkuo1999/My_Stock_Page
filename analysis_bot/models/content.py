from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.tz import now_tw


class News(SQLModel, table=True):
    """News articles and reports scraped from various sources."""

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str = Field(unique=True)
    source: str | None = None
    content: str | None = None  # Description/snippet for search
    type: str = Field(default="news", index=True)  # "news" or "report"
    created_at: datetime = Field(default_factory=now_tw)


class Podcast(SQLModel, table=True):
    """Podcast episodes tracked."""

    id: int | None = Field(default=None, primary_key=True)
    host: str
    title: str
    url: str | None = None  # Added for future proofing
    created_at: datetime = Field(default_factory=now_tw)
