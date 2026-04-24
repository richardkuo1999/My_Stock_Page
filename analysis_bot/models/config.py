from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.tz import now_tw


class SystemConfig(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str  # JSON or CSV string
    description: str | None = None
    updated_at: datetime = Field(default_factory=now_tw)
