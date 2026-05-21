from __future__ import annotations

from datetime import datetime

from app.services import auto_ingest_scheduler


class FakeDB:
    def rollback(self):
        return None


def test_daily_work_runs_once_and_marks_completion(monkeypatch):
    db = FakeDB()
    store: dict[tuple[str, int | None], str] = {}
    queued: list[tuple[int | None, int | None]] = []

    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_enabled", lambda: True)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_run_hour_local", lambda: 6)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_limit", lambda: 50)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_now", lambda: datetime(2026, 5, 19, 9, 0, 0))
    monkeypatch.setattr(auto_ingest_scheduler, "_list_organization_ids", lambda db: [1])
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "get_setting",
        lambda db, key, default="", organization_id=None, user_id=None: store.get((key, organization_id), default),
    )
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "upsert_setting",
        lambda db, key, value, organization_id=None, user_id=None: store.__setitem__((key, organization_id), value),
    )
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "queue_daily_work",
        lambda db, organization_id=None, user_id=None, limit=200: (
            queued.append((organization_id, limit))
            or {
                "queued_count": 3,
                "queueable_items": 3,
                "skipped_backpressure_count": 0,
                "batch_job_id": "batch-1",
            }
        ),
    )

    result = auto_ingest_scheduler.run_daily_work_if_due(db)

    assert result["ran"] == 1
    assert result["completed"] == 1
    assert queued == [(1, 50)]
    assert store[("daily_work_last_run_date", 1)] == "2026-05-19"
    assert store[("daily_work_last_status", 1)] == "completed"

    second = auto_ingest_scheduler.run_daily_work_if_due(db)
    assert second["skipped_already_run"] == 1
    assert queued == [(1, 50)]


def test_daily_work_skips_before_scheduled_hour(monkeypatch):
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_enabled", lambda: True)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_run_hour_local", lambda: 6)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_now", lambda: datetime(2026, 5, 19, 5, 30, 0))

    result = auto_ingest_scheduler.run_daily_work_if_due(FakeDB())

    assert result["ran"] == 0
    assert result["skipped_before_hour"] == 1


def test_daily_work_defers_when_backpressure_present(monkeypatch):
    db = FakeDB()
    store: dict[tuple[str, int | None], str] = {}
    queued_calls = 0

    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_enabled", lambda: True)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_run_hour_local", lambda: 6)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_limit", lambda: 25)
    monkeypatch.setattr(auto_ingest_scheduler, "_daily_work_now", lambda: datetime(2026, 5, 19, 10, 0, 0))
    monkeypatch.setattr(auto_ingest_scheduler, "_list_organization_ids", lambda db: [7])
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "get_setting",
        lambda db, key, default="", organization_id=None, user_id=None: store.get((key, organization_id), default),
    )
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "upsert_setting",
        lambda db, key, value, organization_id=None, user_id=None: store.__setitem__((key, organization_id), value),
    )

    def fake_queue_daily_work(db, organization_id=None, user_id=None, limit=200):
        nonlocal queued_calls
        queued_calls += 1
        return {
            "queued_count": 0,
            "queueable_items": 4,
            "skipped_backpressure_count": 4,
            "batch_job_id": "batch-deferred",
        }

    monkeypatch.setattr(auto_ingest_scheduler, "queue_daily_work", fake_queue_daily_work)

    result = auto_ingest_scheduler.run_daily_work_if_due(db)

    assert result["ran"] == 1
    assert result["deferred_backpressure"] == 1
    assert store[("daily_work_last_status", 7)] == "deferred_backpressure"
    assert ("daily_work_last_run_date", 7) not in store
    assert queued_calls == 1
