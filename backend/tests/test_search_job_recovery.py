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
