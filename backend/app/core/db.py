import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://nagacon:nagacon@localhost:5432/nagacon",
    )
)

def _int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(getattr(settings, name, default) or default))
    except Exception:
        return default


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_int_setting("DB_POOL_SIZE", 8),
    max_overflow=_int_setting("DB_MAX_OVERFLOW", 4),
    pool_timeout=_int_setting("DB_POOL_TIMEOUT_SECONDS", 10),
    pool_recycle=_int_setting("DB_POOL_RECYCLE_SECONDS", 1800),
    pool_use_lifo=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
