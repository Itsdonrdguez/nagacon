from __future__ import annotations

import os

from app.core.config import settings
from app.services.search_jobs import DEFAULT_LANE, QUEUE_LANE, VENDOR_LANE, worker_loop_for_lane


def _resolve_lane() -> str | None:
    configured = str(os.getenv("SEARCH_JOB_WORKER_LANE", "")).strip().lower()
    if configured in {QUEUE_LANE, VENDOR_LANE, DEFAULT_LANE}:
        return configured
    role = str(getattr(settings, "APP_ROLE", "") or "").strip().lower()
    if role == "queue_worker":
        return QUEUE_LANE
    if role == "vendor_worker":
        return VENDOR_LANE
    if role == "search_worker":
        return DEFAULT_LANE
    return None


if __name__ == "__main__":
    worker_loop_for_lane(lane=_resolve_lane())
