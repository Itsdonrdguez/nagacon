from __future__ import annotations

import threading

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.file_retention import prune_eligible_files_for_system


def _auto_file_prune_loop(stop_event: threading.Event) -> None:
    poll_seconds = max(300, int(getattr(settings, "AUTO_FILE_PRUNE_POLL_SECONDS", 21600) or 21600))
    batch_size = max(1, int(getattr(settings, "AUTO_FILE_PRUNE_BATCH_SIZE", 100) or 100))
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            prune_eligible_files_for_system(db, limit=batch_size)
        except Exception:
            db.rollback()
        finally:
            db.close()
        stop_event.wait(poll_seconds)


def start_auto_file_prune_worker(app) -> None:
    if not bool(getattr(settings, "AUTO_FILE_PRUNE_ENABLED", True)):
        return
    if str(getattr(settings, "APP_ROLE", "web") or "web").lower() != "web":
        return
    if getattr(app.state, "auto_file_prune_thread", None):
        return
    stop_event = threading.Event()
    thread = threading.Thread(target=_auto_file_prune_loop, args=(stop_event,), daemon=True, name="nagacon-auto-file-prune")
    app.state.auto_file_prune_stop_event = stop_event
    app.state.auto_file_prune_thread = thread
    thread.start()


def stop_auto_file_prune_worker(app) -> None:
    stop_event = getattr(app.state, "auto_file_prune_stop_event", None)
    thread = getattr(app.state, "auto_file_prune_thread", None)
    if stop_event:
        stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.5)
    app.state.auto_file_prune_thread = None
    app.state.auto_file_prune_stop_event = None
