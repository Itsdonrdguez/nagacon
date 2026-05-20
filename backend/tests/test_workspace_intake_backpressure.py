from __future__ import annotations

from types import SimpleNamespace

from app.api import opportunities as opportunities_api
from app.api import search_jobs as search_jobs_api
from app.services import auto_ingest_scheduler, work_queue


class FakeQuery:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)


class FakeDB:
    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, model):
        return FakeQuery(self.rows)


def test_workspace_intake_backpressure_snapshot_counts_rows(monkeypatch):
    monkeypatch.setattr(work_queue, "_workspace_intake_max_pending", lambda: 6)
    monkeypatch.setattr(work_queue, "_workspace_intake_automation_batch_limit", lambda: 3)
    rows = [
        SimpleNamespace(kind="workspace_intake", status="queued"),
        SimpleNamespace(kind="workspace_intake", status="running"),
        SimpleNamespace(kind="workspace_intake", status="queued"),
        SimpleNamespace(kind="awardee_enrichment", status="queued"),
    ]

    snapshot = work_queue.workspace_intake_backpressure_snapshot(FakeDB(rows), organization_id=1)

    assert snapshot["queued"] == 2
    assert snapshot["running"] == 1
    assert snapshot["pending"] == 3
    assert snapshot["available_slots"] == 3
    assert snapshot["blocked"] is False


def test_queue_daily_work_respects_workspace_intake_backpressure(monkeypatch):
    monkeypatch.setattr(
        work_queue,
        "build_daily_work_queue",
        lambda db, organization_id=None, user_id=None, limit=200: {
            "items": [
                {
                    "id": "closed:1",
                    "type": "CLOSED_WORKSPACE_PREP",
                    "opportunity": {"id": 11},
                    "meta": {"opportunity_fingerprint": "fp-11"},
                },
                {
                    "id": "closed:2",
                    "type": "CLOSED_WORKSPACE_PREP",
                    "opportunity": {"id": 12},
                    "meta": {"opportunity_fingerprint": "fp-12"},
                },
                {
                    "id": "awardee:3",
                    "type": "AWARDEE_ENRICHMENT_READY",
                    "opportunity": {"id": 13},
                    "meta": {"opportunity_fingerprint": "fp-13"},
                },
            ],
            "generated_at": "2026-05-18T12:00:00",
        },
    )
    monkeypatch.setattr(work_queue, "_active_job_signatures", lambda db, organization_id: set())
    monkeypatch.setattr(
        work_queue,
        "workspace_intake_backpressure_snapshot",
        lambda db, organization_id, user_id=None, active_rows=None: {
            "kind": "workspace_intake",
            "queued": 9,
            "running": 1,
            "pending": 10,
            "max_pending": 11,
            "automation_batch_limit": 5,
            "available_slots": 1,
            "blocked": False,
        },
    )
    queued = []
    monkeypatch.setattr(
        work_queue,
        "start_search_job",
        lambda kind, payload: queued.append((kind, payload)) or {"id": f"job-{len(queued)}", "status": "queued"},
    )
    monkeypatch.setattr(work_queue, "record_search_job", lambda *args, **kwargs: {"id": "batch-1"})

    result = work_queue.queue_daily_work(object(), organization_id=1, user_id=7, limit=50)

    assert result["queued_count"] == 2
    assert result["skipped_backpressure_count"] == 1
    assert queued[0][0] == "workspace_intake"
    assert queued[1][0] == "awardee_enrichment"


def test_closed_workspace_auto_queue_skips_when_backpressure_blocked(monkeypatch):
    candidates = [
        SimpleNamespace(id=21, organization_id=1, parsed_json={"nsn": "5306000039356"}),
        SimpleNamespace(id=22, organization_id=1, parsed_json={}),
    ]
    monkeypatch.setattr(auto_ingest_scheduler, "_closed_workspace_prep_enabled", lambda: True)
    monkeypatch.setattr(auto_ingest_scheduler, "_recently_closed_candidates", lambda db, now: candidates)
    monkeypatch.setattr(auto_ingest_scheduler, "_count_by_opportunity", lambda *args, **kwargs: {})
    monkeypatch.setattr(auto_ingest_scheduler, "_existing_workspace_intake_jobs", lambda db, opp_ids, now: set())
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "workspace_intake_backpressure_snapshot",
        lambda db, organization_id, user_id=None, active_rows=None: {
            "kind": "workspace_intake",
            "queued": 24,
            "running": 2,
            "pending": 26,
            "max_pending": 24,
            "automation_batch_limit": 5,
            "available_slots": 0,
            "blocked": True,
        },
    )
    queued = []
    monkeypatch.setattr(auto_ingest_scheduler, "start_search_job", lambda kind, payload: queued.append((kind, payload)))

    result = auto_ingest_scheduler.queue_recently_closed_workspace_prep(object())

    assert result["queued"] == 0
    assert result["skipped_backpressure"] == 2
    assert queued == []


def test_auto_workspace_prep_queues_only_missing_candidates(monkeypatch):
    candidates = [
        SimpleNamespace(id=41, organization_id=1, source="DIBBS", parsed_json={"nsn": "5306000039356"}, due_at=None),
        SimpleNamespace(id=42, organization_id=1, source="SAM", parsed_json={}, due_at=None),
        SimpleNamespace(id=43, organization_id=1, source="DIBBS", parsed_json={}, due_at=None),
    ]
    monkeypatch.setattr(auto_ingest_scheduler, "_auto_workspace_prep_enabled", lambda **kwargs: True)
    monkeypatch.setattr(auto_ingest_scheduler, "_auto_workspace_prep_limit", lambda: 5)
    monkeypatch.setattr(auto_ingest_scheduler, "_workspace_prep_candidates", lambda db, now, organization_id=None: candidates)
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "_count_by_opportunity",
        lambda db, model, opp_ids, artifact_type=None: (
            {41: 1, 42: 0, 43: 1}
            if model.__name__ == "OpportunityFile"
            else {41: 1, 42: 1, 43: 1}
            if model.__name__ == "VendorLead"
            else {41: 1, 42: 1, 43: 1}
            if artifact_type == "SUBMISSION_PACKAGE"
            else {41: 0, 42: 1, 43: 1}
            if artifact_type == "PART_FINDER"
            else {41: 1, 42: 1, 43: 1}
            if artifact_type == "NSN_INTELLIGENCE"
            else {41: 1, 42: 0, 43: 1}
            if artifact_type == "CHECKLIST"
            else {}
        ),
    )
    monkeypatch.setattr(auto_ingest_scheduler, "_existing_workspace_intake_jobs", lambda db, opp_ids, now: {43})
    monkeypatch.setattr(
        auto_ingest_scheduler,
        "workspace_intake_backpressure_snapshot",
        lambda db, organization_id, user_id=None, active_rows=None: {
            "kind": "workspace_intake",
            "queued": 0,
            "running": 0,
            "pending": 0,
            "max_pending": 24,
            "automation_batch_limit": 5,
            "available_slots": 3,
            "blocked": False,
        },
    )
    monkeypatch.setattr(auto_ingest_scheduler, "_mark_workspace_prep_attempt", lambda *args, **kwargs: None)
    queued = []
    monkeypatch.setattr(auto_ingest_scheduler, "start_search_job", lambda kind, payload: queued.append((kind, payload)))

    result = auto_ingest_scheduler.queue_workspace_prep_for_opportunities(object(), organization_id=1, manual=False)

    assert result["queued"] == 2
    assert result["skipped_existing"] == 0
    assert queued[0][1]["opportunity_id"] == 41
    assert queued[1][1]["opportunity_id"] == 42


def test_bulk_prepare_workspace_skips_when_backpressure_full(client, monkeypatch):
    opp = SimpleNamespace(id=31, title="Valve", display_title="Valve", opportunity_lifecycle="ACTIVE")

    class FakeRepo:
        def get(self, opportunity_id):
            return opp if int(opportunity_id) == 31 else None

    class EmptyQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class RouteDB:
        def query(self, model):
            return EmptyQuery()

    monkeypatch.setattr(opportunities_api, "_opportunity_repo", lambda db, org_id: FakeRepo())
    monkeypatch.setattr(
        opportunities_api,
        "workspace_intake_backpressure_snapshot",
        lambda db, organization_id, user_id=None, active_rows=None: {
            "kind": "workspace_intake",
            "queued": 24,
            "running": 2,
            "pending": 26,
            "max_pending": 24,
            "automation_batch_limit": 5,
            "available_slots": 0,
            "blocked": True,
        },
    )

    def override_get_db():
        yield RouteDB()

    client.app.dependency_overrides[opportunities_api.get_db] = override_get_db
    response = client.post("/api/opportunities/bulk/workspace-intake", json={"opportunity_ids": [31]})
    client.app.dependency_overrides.pop(opportunities_api.get_db, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["queued_count"] == 0
    assert payload["skipped_backpressure_count"] == 1
    assert payload["workspace_intake_backpressure"]["blocked"] is True


def test_search_jobs_workspace_intake_returns_429_when_backpressure_blocked(client, monkeypatch):
    monkeypatch.setattr(
        search_jobs_api,
        "workspace_intake_backpressure_snapshot",
        lambda db, organization_id, user_id=None, active_rows=None: {
            "kind": "workspace_intake",
            "queued": 24,
            "running": 2,
            "pending": 26,
            "max_pending": 24,
            "automation_batch_limit": 5,
            "available_slots": 0,
            "blocked": True,
        },
    )

    response = client.post("/api/search-jobs", json={"kind": "workspace_intake", "opportunity_id": 99})

    assert response.status_code == 429
    payload = response.json()
    assert payload["detail"]["workspace_intake_backpressure"]["blocked"] is True
