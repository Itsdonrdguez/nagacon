from __future__ import annotations

from datetime import datetime, timedelta


def derive_solicitation_status(due_at: datetime | None, *, now: datetime | None = None) -> str:
    if due_at is None:
        return "OPEN"

    current_time = now or datetime.utcnow()
    if due_at < current_time:
        return "CLOSED"
    if due_at <= current_time + timedelta(days=7):
        return "DUE_SOON"
    return "OPEN"
