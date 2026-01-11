from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class StockData(SQLModel, table=True):
    """Stocks analyzed by the bot (manual esti or daily run)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True, unique=True)
    name: Optional[str] = None
    tag: Optional[str] = None
    sector: Optional[str] = None
    price: Optional[float] = None
    data: Optional[str] = None  # JSON string of full analysis result
    last_analyzed: datetime = Field(default_factory=datetime.utcnow)




