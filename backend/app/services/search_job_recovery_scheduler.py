from __future__ import annotations

import threading

from app.core.config import settings
from app.services.search_jobs import recover_stale_jobs_now, uses_external_worker


def _recovery_poll_seconds() -> int:
    try:
        return max(5, int(getattr(settings, "SEARCH_JOB_RECOVERY_POLL_SECONDS", 30) or 30))
    except Exception:
        return 30


def _recovery_enabled() -> bool:
    if uses_external_worker():
        return False
    return str(getattr(settings, "APP_ROLE", "web") or "web").lower() == "web"


def _recovery_loop(stop_event: threading.Event) -> None:
    delay = _recovery_poll_seconds()
    while not stop_event.is_set():
        try:
            recover_stale_jobs_now()
        except Exception:
            pass
        stop_event.wait(delay)


def start_search_job_recovery_worker(app) -> None:
    if not _recovery_enabled():
        return
    if getattr(app.state, "search_job_recovery_thread", None):
        return
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_recovery_loop,
        args=(stop_event,),
        daemon=True,
        name="nagacon-search-job-recovery",
    )
    app.state.search_job_recovery_stop_event = stop_event
    app.state.search_job_recovery_thread = thread
    thread.start()


def stop_search_job_recovery_worker(app) -> None:
    stop_event = getattr(app.state, "search_job_recovery_stop_event", None)
    thread = getattr(app.state, "search_job_recovery_thread", None)
    if stop_event:
        stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.5)
    app.state.search_job_recovery_thread = None
    app.state.search_job_recovery_stop_event = None
