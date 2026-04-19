from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.awardee_enrichment import award_followup_status
from app.services.providers.identity_resolver import resolve_provider_identity


def test_award_followup_status_waits_90_days_after_close():
    now = datetime(2026, 4, 19, 12, 0, 0)
    recent = SimpleNamespace(due_at=now - timedelta(days=45))
    due = SimpleNamespace(due_at=now - timedelta(days=120))

    recent_status = award_followup_status(recent, now=now)
    due_status = award_followup_status(due, now=now)

    assert recent_status["status"] == "AWAITING_USASPENDING"
    assert recent_status["follow_up_eligible"] is False
    assert due_status["status"] == "READY_FOR_USASPENDING_CHECK"
    assert due_status["follow_up_eligible"] is True
    assert due_status["award_expected_after"] == due.due_at + timedelta(days=90)


def test_resolve_provider_identity_uses_official_cage_profile():
    evidence = SimpleNamespace(raw_payload={"COMPANY": "Acme Defense Inc."})
    provider = SimpleNamespace(
        id=7,
        company_name="CAGE 1ABC2",
        cage="1ABC2",
        canonical_name=None,
        identity_source=None,
        identity_confidence=None,
        aliases=[],
    )

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return evidence

    class FakeDB:
        def query(self, model):
            return Query()

        def add(self, item):
            self.item = item

    result = resolve_provider_identity(FakeDB(), provider)

    assert result["canonical_name"] == "Acme Defense Inc."
    assert result["identity_source"] == "PUB_LOG_P_CAGE"
    assert result["identity_confidence"] == 95.0
    assert provider.company_name == "Acme Defense Inc."
    assert "CAGE 1ABC2" in result["aliases"]
