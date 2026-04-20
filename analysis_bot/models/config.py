from datetime import datetime

from sqlmodel import Field, SQLModel


class SystemConfig(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str  # JSON or CSV string
    description: str | None = None
    updated_at: datetime = Field(default_factory=datetime.now)
