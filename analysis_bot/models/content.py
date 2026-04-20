from datetime import datetime

from sqlmodel import Field, SQLModel


class News(SQLModel, table=True):
    """News articles scraped from various sources."""

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str = Field(unique=True)
    source: str | None = None
    content: str | None = None  # Description/snippet for search (RSS description or API content)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Report(SQLModel, table=True):
    """Analysis reports found online."""

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str
    created_at: datetime = Field(default_factory=datetime.now)


class Podcast(SQLModel, table=True):
    """Podcast episodes tracked."""

    id: int | None = Field(default=None, primary_key=True)
    host: str
    title: str
    url: str | None = None  # Added for future proofing
    created_at: datetime = Field(default_factory=datetime.now)
