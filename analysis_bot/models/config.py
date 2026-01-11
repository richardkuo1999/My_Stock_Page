from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class SystemConfig(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str # JSON or CSV string
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.now)
