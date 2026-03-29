from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class News(SQLModel, table=True):
    """News articles scraped from various sources."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str = Field(unique=True)
    source: Optional[str] = None
    content: Optional[str] = None  # Description/snippet for search (RSS description or API content)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Report(SQLModel, table=True):
    """Analysis reports found online."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str
    created_at: datetime = Field(default_factory=datetime.now)

class Podcast(SQLModel, table=True):
    """Podcast episodes tracked."""
    id: Optional[int] = Field(default=None, primary_key=True)
    host: str
    title: str
    url: Optional[str] = None # Added for future proofing
    created_at: datetime = Field(default_factory=datetime.now)
