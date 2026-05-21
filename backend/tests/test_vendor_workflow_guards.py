from types import SimpleNamespace

import pytest

from app.services import vendor_service


class FakeDB:
    def __init__(self, quote=None):
        self.quote = quote
        self.commits = 0

    def query(self, model):
        quote = self.quote

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return quote

        return FakeQuery()

    def add(self, item):
        return None

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        return None

    def flush(self):
        return None


@pytest.fixture(autouse=True)
def _stub_workflow_event(monkeypatch):
    monkeypatch.setattr(vendor_service, "record_workflow_event", lambda *args, **kwargs: None)


def test_upsert_quote_requires_explicit_approval_for_requested_status():
    quote = SimpleNamespace(
        id=3,
        opportunity_id=9,
        organization_id=1,
        cage="1ABC2",
        part_number=None,
        status="NOT_REQUESTED",
        email="vendor@example.com",
        phone=None,
        contact_name="Vendor Contact",
        company_name="Vendor Co",
        unit_price=None,
        notes=None,
        requested_at=None,
        next_follow_up_at=None,
        updated_at=None,
    )
    db = FakeDB(quote=quote)

    with pytest.raises(ValueError) as exc:
        vendor_service.upsert_quote(
            db,
            9,
            "1ABC2",
            None,
            {"status": "REQUESTED"},
            organization_id=1,
            user_id=2,
        )

    assert "explicit approval is required" in str(exc.value)


def test_upsert_quote_allows_requested_status_with_approval():
    quote = SimpleNamespace(
        id=4,
        opportunity_id=9,
        organization_id=1,
        cage="1ABC2",
        part_number=None,
        status="NOT_REQUESTED",
        email="vendor@example.com",
        phone=None,
        contact_name="Vendor Contact",
        company_name="Vendor Co",
        unit_price=None,
        notes=None,
        requested_at=None,
        next_follow_up_at=None,
        updated_at=None,
    )
    db = FakeDB(quote=quote)

    result = vendor_service.upsert_quote(
        db,
        9,
        "1ABC2",
        None,
        {"status": "REQUESTED", "approved": True, "approval_notes": "Sales approved"},
        organization_id=1,
        user_id=2,
    )

    assert result.status == "REQUESTED"
    assert db.commits == 1


def test_upsert_quote_requires_explicit_approval_for_received_without_requested_state():
    quote = SimpleNamespace(
        id=5,
        opportunity_id=9,
        organization_id=1,
        cage="1ABC2",
        part_number=None,
        status="NOT_REQUESTED",
        email="vendor@example.com",
        phone=None,
        contact_name="Vendor Contact",
        company_name="Vendor Co",
        unit_price=19.5,
        notes=None,
        requested_at=None,
        next_follow_up_at=None,
        updated_at=None,
    )
    db = FakeDB(quote=quote)

    with pytest.raises(ValueError) as exc:
        vendor_service.upsert_quote(
            db,
            9,
            "1ABC2",
            None,
            {"status": "RECEIVED", "unit_price": 19.5},
            organization_id=1,
            user_id=2,
        )

    assert "explicit approval is required" in str(exc.value)
