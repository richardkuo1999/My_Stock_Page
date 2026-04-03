# Data Models

## Overview
All models are SQLModel-based and defined in `analysis_bot/models/`.

## Model Definitions

### StockData (`stock.py`)
```python
class StockData(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True, unique=True)
    name: Optional[str] = None
    tag: Optional[str] = None        # Comma-separated tags (ETF, Institutional, etc.)
    sector: Optional[str] = None
    price: Optional[float] = None
    data: Optional[str] = None      # JSON string of full analysis result
    last_analyzed: datetime = Field(default_factory=datetime.utcnow)
```

**Purpose:** Cache stock analysis results with 6-hour TTL.

---

### Subscriber (`subscriber.py`)
```python
class Subscriber(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)
```

**Purpose:** Track Telegram chat IDs for push notifications.

---

### WatchlistEntry (`watchlist.py`)
```python
class WatchlistEntry(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "ticker", name="uq_watchlist_chat_user_ticker"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    user_id: int = Field(index=True)
    ticker: str = Field(index=True)
    alias: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Purpose:** Per-chat, per-user stock watchlist with custom aliases.

**Relationships:**
- Many watchlist entries can reference one `Subscriber` (by chat_id)
- Many watchlist entries can reference one `StockData` (by ticker) - implicit

---

### News (`content.py`)
```python
class News(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str = Field(unique=True)
    source: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Purpose:** Deduplication of fetched news articles.

---

### Report (`content.py`)
```python
class Report(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    link: str
    created_at: datetime = Field(default_factory=datetime.now)
```

**Purpose:** Track analysis reports found online.

---

### Podcast (`content.py`)
```python
class Podcast(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    host: str
    title: str
    url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
```

**Purpose:** Track podcast episodes for processing.

---

### SystemConfig (`config.py`)
```python
class SystemConfig(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str  # JSON or CSV string
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.now)
```

**Purpose:** Store system-wide configuration (e.g., `active_daily_tags`).

---

## Entity Relationship Diagram

```
┌─────────────────┐
│   Subscriber    │
│─────────────────│
│ chat_id (PK)    │◄──────┐
│ is_active       │       │
└─────────────────┘       │
                          │ (same chat_id)
┌─────────────────┐       │
│ WatchlistEntry  │───────┘
│─────────────────│
│ chat_id (FK)    │
│ user_id         │
│ ticker          │───────┐
│ alias           │       │
└─────────────────┘       │ (same ticker)
                          │
┌─────────────────┐       │
│   StockData     │◄──────┘
│─────────────────│
│ ticker (PK)     │
│ name            │
│ tag             │
│ data (JSON)     │
│ last_analyzed   │
└─────────────────┘

┌─────────────────┐     ┌─────────────────┐
│      News       │     │     Report      │
│─────────────────│     │─────────────────│
│ title           │     │ title           │
│ link (UK)       │     │ link            │
│ source          │     │ created_at      │
│ created_at      │     └─────────────────┘
└─────────────────┘
```

## Adding a New Model

1. Create file in `analysis_bot/models/`
2. Import in `models/__init__.py`
3. Create table migration if using Alembic (currently auto-creates on startup)
4. Use in services via `Session(engine)` context manager