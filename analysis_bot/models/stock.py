from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.tz import now_tw


class StockData(SQLModel, table=True):
    """Stocks analyzed by the bot (manual esti or daily run)."""

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True, unique=True)
    name: str | None = None
    tag: str | None = None
    sector: str | None = None
    price: float | None = None
    data: str | None = None  # JSON string of full analysis result
    last_analyzed: datetime = Field(default_factory=now_tw)
