from __future__ import annotations

from datetime import datetime, timedelta
from app.utils.utc import utcnow

ARCHIVE_CUTOFF_DAYS = 30


def derive_opportunity_lifecycle(due_at: datetime | None, *, now: datetime | None = None) -> str:
    current_time = now or utcnow()
    if due_at is None or due_at >= current_time:
        return "ACTIVE"
    if due_at >= current_time - timedelta(days=ARCHIVE_CUTOFF_DAYS):
        return "RECENTLY_CLOSED"
    return "ARCHIVED"


def is_archived_opportunity(due_at: datetime | None, *, now: datetime | None = None) -> bool:
    return derive_opportunity_lifecycle(due_at, now=now) == "ARCHIVED"
