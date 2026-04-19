from __future__ import annotations

import threading
import time

from app.core.db import SessionLocal
from app.repositories.company import CompanyRepository
from app.services.company_profile_ingest import company_profile_due_for_auto_ingest, run_company_profile_ingest


AUTO_INGEST_POLL_SECONDS = 900


def _auto_ingest_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            profile = CompanyRepository(db).get_first_profile()
            if company_profile_due_for_auto_ingest(profile):
                run_company_profile_ingest(db, profile)
        except Exception:
            db.rollback()
        finally:
            db.close()
        stop_event.wait(AUTO_INGEST_POLL_SECONDS)


def start_auto_ingest_worker(app) -> None:
    if getattr(app.state, "auto_ingest_thread", None):
        return
    stop_event = threading.Event()
    thread = threading.Thread(target=_auto_ingest_loop, args=(stop_event,), daemon=True, name="nagacon-auto-ingest")
    app.state.auto_ingest_stop_event = stop_event
    app.state.auto_ingest_thread = thread
    thread.start()


def stop_auto_ingest_worker(app) -> None:
    stop_event = getattr(app.state, "auto_ingest_stop_event", None)
    thread = getattr(app.state, "auto_ingest_thread", None)
    if stop_event:
        stop_event.set()
    if thread and thread.is_alive():
        thread.join(timeout=1.5)
    app.state.auto_ingest_thread = None
    app.state.auto_ingest_stop_event = None
