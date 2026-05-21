from types import SimpleNamespace

import pytest

from app.services import bid_submission_service


class FakeDB:
    def __init__(self, submission=None):
        self.submission = submission
        self.added = []
        self.commits = 0

    def add(self, item):
        self.added.append(item)
        if self.submission is None and getattr(item, "opportunity_id", None):
            item.id = getattr(item, "id", 1) or 1
            self.submission = item

    def flush(self):
        return None

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        return None


@pytest.fixture(autouse=True)
def _stub_workflow_event(monkeypatch):
    monkeypatch.setattr(bid_submission_service, "record_workflow_event", lambda *args, **kwargs: None)


def test_upsert_submission_rejects_submitted_without_price_or_vendor(monkeypatch):
    db = FakeDB(submission=SimpleNamespace(id=1, opportunity_id=7, status="DRAFT"))
    monkeypatch.setattr(bid_submission_service, "get_submission", lambda db_arg, opportunity_id: db.submission)

    with pytest.raises(ValueError) as exc:
        bid_submission_service.upsert_submission(
            db,
            7,
            {"status": "SUBMITTED", "approved": True},
            organization_id=1,
            user_id=2,
            opportunity=SimpleNamespace(id=7, organization_id=1),
        )

    assert "submitted_unit_price is required" in str(exc.value)


def test_upsert_submission_rejects_awarded_before_submitted(monkeypatch):
    db = FakeDB(submission=SimpleNamespace(id=1, opportunity_id=7, status="DRAFT"))
    monkeypatch.setattr(bid_submission_service, "get_submission", lambda db_arg, opportunity_id: db.submission)

    with pytest.raises(ValueError) as exc:
        bid_submission_service.upsert_submission(
            db,
            7,
            {"status": "AWARDED"},
            organization_id=1,
            user_id=2,
            opportunity=SimpleNamespace(id=7, organization_id=1),
        )

    assert "cannot move from DRAFT to AWARDED" in str(exc.value)


def test_upsert_submission_allows_hardened_submitted_transition(monkeypatch):
    submission = SimpleNamespace(
        id=1,
        opportunity_id=7,
        status="DRAFT",
        submitted_unit_price=None,
        submitted_vendor_cage=None,
        submitted_vendor_name=None,
        planned_vendor_quote_id=None,
        updated_at=None,
    )
    db = FakeDB(submission=submission)
    monkeypatch.setattr(bid_submission_service, "get_submission", lambda db_arg, opportunity_id: submission)

    result = bid_submission_service.upsert_submission(
        db,
        7,
        {
            "status": "SUBMITTED",
            "approved": True,
            "submitted_unit_price": 22.5,
            "submitted_vendor_cage": "1ABC2",
        },
        organization_id=1,
        user_id=2,
        opportunity=SimpleNamespace(id=7, organization_id=1),
    )

    assert result.status == "SUBMITTED"
    assert float(result.submitted_unit_price) == 22.5
    assert result.submitted_vendor_cage == "1ABC2"


def test_upsert_submission_requires_explicit_approval(monkeypatch):
    submission = SimpleNamespace(
        id=1,
        opportunity_id=7,
        status="DRAFT",
        submitted_unit_price=None,
        submitted_vendor_cage=None,
        submitted_vendor_name=None,
        planned_vendor_quote_id=None,
        updated_at=None,
    )
    db = FakeDB(submission=submission)
    monkeypatch.setattr(bid_submission_service, "get_submission", lambda db_arg, opportunity_id: submission)

    with pytest.raises(ValueError) as exc:
        bid_submission_service.upsert_submission(
            db,
            7,
            {
                "status": "SUBMITTED",
                "submitted_unit_price": 22.5,
                "submitted_vendor_cage": "1ABC2",
            },
            organization_id=1,
            user_id=2,
            opportunity=SimpleNamespace(id=7, organization_id=1),
        )

    assert "explicit approval is required" in str(exc.value)


def test_upsert_submission_requires_explicit_approval_for_awarded_transition(monkeypatch):
    submission = SimpleNamespace(
        id=1,
        opportunity_id=7,
        status="SUBMITTED",
        submitted_unit_price=22.5,
        submitted_vendor_cage="1ABC2",
        submitted_vendor_name=None,
        planned_vendor_quote_id=None,
        updated_at=None,
        award_amount=None,
        winning_vendor_cage=None,
        winning_vendor_name=None,
    )
    db = FakeDB(submission=submission)
    monkeypatch.setattr(bid_submission_service, "get_submission", lambda db_arg, opportunity_id: submission)

    with pytest.raises(ValueError) as exc:
        bid_submission_service.upsert_submission(
            db,
            7,
            {"status": "AWARDED", "award_amount": 1000},
            organization_id=1,
            user_id=2,
            opportunity=SimpleNamespace(id=7, organization_id=1),
        )

    assert "explicit approval is required" in str(exc.value)
