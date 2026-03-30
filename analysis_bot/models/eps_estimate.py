from datetime import datetime

from sqlmodel import Field, SQLModel


class EpsEstimate(SQLModel, table=True):
    """Historical FactSet EPS estimate snapshots from 鉅亨網."""

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    est_eps: float
    est_price: float | None = None
    source_date: datetime = Field(index=True)
    source_url: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
