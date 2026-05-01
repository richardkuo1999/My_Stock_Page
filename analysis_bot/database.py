from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()

# check_same_thread=False is needed for SQLite with FastAPI/Async
engine = create_engine(
    settings.DATABASE_URL, echo=settings.DEBUG, connect_args={"check_same_thread": False}
)

from sqlalchemy import event, text


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_db_and_tables():
    # Helper to import all models so SQLModel metadata is populated
    from .models import intraday_ma  # noqa: F401 — ensures IntradayMA20Snapshot is registered
    from .models import sentiment  # noqa: F401 — ensures NewsSentiment is registered
    from .models import gsheet_sub  # noqa: F401 — ensures GSheetSubscription is registered

    SQLModel.metadata.create_all(engine)

    # Migration: add columns if missing (SQLite)
    if "sqlite" in settings.DATABASE_URL:
        with engine.connect() as conn:
            # Drop legacy unique index on chat_id alone (blocks group multi-topic subs)
            try:
                conn.execute(text("DROP INDEX IF EXISTS ix_subscriber_chat_id"))
                conn.commit()
            except Exception:
                pass
            # Ensure composite unique index exists
            try:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriber_chat_topic "
                    "ON subscriber (chat_id, topic_id)"
                ))
                conn.commit()
            except Exception:
                pass
            for ddl in [
                "ALTER TABLE news ADD COLUMN content TEXT",
                "ALTER TABLE intraday_ma20_snapshot ADD COLUMN vol_19d_sum_lots REAL",
                "ALTER TABLE subscriber ADD COLUMN ispike_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN sentiment_alert_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN news_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN umon_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN topic_id INTEGER",
                "ALTER TABLE threadswatchentry ADD COLUMN topic_id INTEGER",
                "ALTER TABLE news ADD COLUMN type TEXT DEFAULT 'news'",
                "ALTER TABLE watchlist_entry ADD COLUMN added_price REAL",
                "ALTER TABLE watchlist_entry ADD COLUMN user_name TEXT",
                "ALTER TABLE watchlist_entry ADD COLUMN note TEXT",
                "ALTER TABLE watchlist_entry ADD COLUMN source TEXT",
                "ALTER TABLE gsheet_subscription ADD COLUMN user_name TEXT",
                "ALTER TABLE subscriber ADD COLUMN daily_analysis_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN spike_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN vix_enabled INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE subscriber ADD COLUMN wlist_enabled INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    conn.execute(text(ddl))
                    conn.commit()
                except Exception as e:
                    err = str(e).lower()
                    if "duplicate column" not in err and "already exists" not in err:
                        raise


def get_session():
    with Session(engine) as session:
        yield session
