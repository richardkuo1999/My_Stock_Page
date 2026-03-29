from sqlmodel import create_engine, SQLModel, Session
from .config import get_settings

settings = get_settings()

# check_same_thread=False is needed for SQLite with FastAPI/Async
engine = create_engine(
    settings.DATABASE_URL, 
    echo=settings.DEBUG, 
    connect_args={"check_same_thread": False}
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
    from .models.stock import StockData
    from .models.subscriber import Subscriber
    from .models.config import SystemConfig
    from .models.content import News, Report, Podcast
    from .models.watchlist import WatchlistEntry
    from .models.eps_estimate import EpsEstimate
    from .models.threads_watch import ThreadsWatchEntry

    SQLModel.metadata.create_all(engine)

    # Migration: add News.content if missing (SQLite)
    if "sqlite" in settings.DATABASE_URL:
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE news ADD COLUMN content TEXT"))
                conn.commit()
            except Exception as e:
                err = str(e).lower()
                if "duplicate column" not in err and "already exists" not in err:
                    raise

def get_session():
    with Session(engine) as session:
        yield session
