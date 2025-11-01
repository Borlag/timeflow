from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import DB_PATH

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}, pool_pre_ping=True
)

# Enable WAL for better concurrency on SQLite and set busy timeout
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def init_db():
    from models import Base  # noqa: F401
    Base.metadata.create_all(bind=engine)
