from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services import search_jobs


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    def all(self):
        return list(self.rows)


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return FakeQuery(self.rows)

    def close(self):
        return None


def test_recover_queued_jobs_for_thread_runner_submits_orphaned_rows(monkeypatch):
    now = datetime.utcnow() - timedelta(minutes=10)
    row = SimpleNamespace(
        id="job-1",
        kind="workspace_intake",
        organization_id=1,
        user_id=2,
        status="queued",
        payload={"opportunity_id": 99, "worker_lane": search_jobs.QUEUE_LANE},
        progress={"percent": 0},
        result=None,
        error=None,
        started_at=None,
        completed_at=None,
        events=[],
        created_at=now,
    )
    submitted = []

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append(args)

    monkeypatch.setattr(search_jobs, "SessionLocal", lambda: FakeDB([row]))
    monkeypatch.setattr(search_jobs, "_thread_executor", lambda lane: FakeExecutor())
    monkeypatch.setattr(search_jobs, "uses_external_worker", lambda: False)
    monkeypatch.setattr(search_jobs, "_recovery_batch_size", lambda: 5)
    monkeypatch.setattr(search_jobs, "_queued_recovery_cutoff", lambda: datetime.utcnow())
    monkeypatch.setattr(search_jobs, "_persist_job", lambda job: None)
    with search_jobs._lock:
        search_jobs._jobs.clear()

    recovered = search_jobs.recover_queued_jobs_for_thread_runner(limit=5)

    assert recovered == 1
    assert submitted == [("job-1", "workspace_intake", {"opportunity_id": 99, "worker_lane": search_jobs.QUEUE_LANE})]


def test_recover_queued_jobs_for_thread_runner_skips_jobs_already_in_memory(monkeypatch):
    now = datetime.utcnow() - timedelta(minutes=10)
    row = SimpleNamespace(
        id="job-2",
        kind="workspace_intake",
        organization_id=1,
        user_id=2,
        status="queued",
        payload={"opportunity_id": 100, "worker_lane": search_jobs.QUEUE_LANE},
        progress={"percent": 0},
        result=None,
        error=None,
        started_at=None,
        completed_at=None,
        events=[],
        created_at=now,
    )
    submitted = []

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append(args)

    monkeypatch.setattr(search_jobs, "SessionLocal", lambda: FakeDB([row]))
    monkeypatch.setattr(search_jobs, "_thread_executor", lambda lane: FakeExecutor())
    monkeypatch.setattr(search_jobs, "uses_external_worker", lambda: False)
    monkeypatch.setattr(search_jobs, "_queued_recovery_cutoff", lambda: datetime.utcnow())
    monkeypatch.setattr(search_jobs, "_persist_job", lambda job: None)
    with search_jobs._lock:
        search_jobs._jobs.clear()
        search_jobs._jobs["job-2"] = {"id": "job-2", "kind": "workspace_intake", "status": "queued", "payload": row.payload, "progress": {}, "events": []}

    recovered = search_jobs.recover_queued_jobs_for_thread_runner(limit=5)

    assert recovered == 0
    assert submitted == []
    with search_jobs._lock:
        search_jobs._jobs.clear()


def test_run_job_records_import_run_for_background_processing(monkeypatch):
    started = {}
    completed = {}

    class DummyGate:
        def acquire(self):
            return True

        def release(self):
            return True

    class FakeDB:
        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(search_jobs, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(search_jobs, "_active_execution_gate", lambda: DummyGate())
    monkeypatch.setattr(search_jobs, "_background_execution_gate", lambda: DummyGate())
    monkeypatch.setattr(search_jobs, "_background_execution_limit", lambda: 0)
    monkeypatch.setattr(search_jobs, "_update_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(search_jobs, "_maybe_refresh_master_catalog_export", lambda *args, **kwargs: None)
    monkeypatch.setattr(search_jobs, "write_worker_traceback_report", lambda **kwargs: "report.json")
    monkeypatch.setattr(
        search_jobs,
        "run_provider_backfill",
        lambda db, **kwargs: {"status": "ok", "row_count": 4, "updated_count": 2, "skipped_count": 1},
    )
    monkeypatch.setattr(
        search_jobs,
        "start_import_run",
        lambda db, **kwargs: started.setdefault("run", SimpleNamespace(id=55, **kwargs)),
    )
    monkeypatch.setattr(
        search_jobs,
        "complete_import_run",
        lambda db, rec, **kwargs: completed.setdefault("payload", {"run_id": rec.id, **kwargs}),
    )

    search_jobs._run_job(
        "job-import-1",
        "provider_backfill",
        {"organization_id": 1, "user_id": 7, "limit": 25},
    )

    assert started["run"].source == "PROVIDER_BACKFILL"
    assert completed["payload"]["status"] == "success"
    assert completed["payload"]["row_count"] == 4
    assert completed["payload"]["updated_count"] == 2
