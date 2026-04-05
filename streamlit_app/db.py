from __future__ import annotations

import os
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_DB_URL = "postgresql+psycopg://nagacon:nagacon@localhost:5432/nagacon"

def get_db_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)

@contextmanager
def get_engine() -> Engine:
    eng = create_engine(get_db_url(), pool_pre_ping=True)
    try:
        yield eng
    finally:
        eng.dispose()
