from datetime import datetime
from types import SimpleNamespace

from app.schemas.opportunity import RawOpportunity
from app.models.provider import Provider
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceArtifact
from app.services import part_vendor_leads
from app.services.part_vendor_leads import (
    _build_part_finder_candidates,
    create_email_drafts_for_part_finder_quotes,
    seed_quotes_from_part_finder_leads,
)
from app.services.part_finder import _target_from_opportunity, find_parts_batch
from app.services.vendor_service import add_business_days, build_quote_follow_up_summary, mark_quote_followed_up, sync_quote_status_from_outreach_artifact


def test_part_finder_extracts_part_target_from_dibbs_search_row():
    opp = SimpleNamespace(
        raw_payload={
            "dibbs_search_row": {
                "nsn": "6515-01-646-2617",
                "quantity": "8",
                "nomenclature": "TOURNIQUET, NONPNEUM",
                "pr_number": "7016356150",
            }
        },
        solicitation_number="6515-01-646-2617",
        source_opportunity_id="SPE2DS26T9653",
        title="TOURNIQUET, NONPNEUM",
    )

    target = _target_from_opportunity(opp)

    assert target["nsn"] == "6515-01-646-2617"
    assert target["compact_nsn"] == "6515016462617"
    assert target["quantity"] == "8"
    assert target["quantity_display"] == "Qty: 8"
    assert target["nomenclature"] == "TOURNIQUET, NONPNEUM"


def test_part_finder_batch_calls_opportunity_and_nsn_finders(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "app.services.part_finder.find_part_for_opportunity",
        lambda db, opportunity_id, organization_id=None: calls.append(("opp", opportunity_id, organization_id)) or {"status": "ok", "id": opportunity_id},
    )
    monkeypatch.setattr(
        "app.services.part_finder.find_part_for_nsn",
        lambda db, nsn, organization_id=None: calls.append(("nsn", nsn, organization_id)) or {"status": "ok", "nsn": nsn},
    )

    result = find_parts_batch(object(), opportunity_ids=[1, 2], nsns=["4110015342682"], organization_id=9, limit=10)

    assert result["count"] == 3
    assert calls == [("opp", 1, 9), ("opp", 2, 9), ("nsn", "4110015342682", 9)]


def test_dibbs_scraper_ingest_auto_runs_part_finder_enrichment(monkeypatch):
    from app.api import scrapers as scrapers_api

    calls = []

    monkeypatch.setattr(scrapers_api, "upsert_raw_opportunity", lambda db, raw, force_refresh=True, organization_id=None: "inserted")
    monkeypatch.setattr(scrapers_api, "find_existing_opportunity", lambda db, raw: type("Opp", (), {"id": 88})())

    def fake_enrich(db, opportunity_ids, organization_id=None, queue_nsn_build=False, max_items=25):
        calls.append((list(opportunity_ids), organization_id, queue_nsn_build, max_items))
        return {"status": "completed", "processed": len(opportunity_ids)}

    monkeypatch.setattr(scrapers_api, "enrich_dibbs_opportunities_after_ingest", fake_enrich)

    result = scrapers_api._ingest_many(
        object(),
        [
            RawOpportunity(
                source="DIBBS",
                source_opportunity_id="6515-01-646-2617",
                solicitation_number="SPE2DS26T9653",
                title="Medical Part",
                agency="DLA",
                url="https://example.test/rfq",
            )
        ],
        auto_enrich_dibbs=True,
        queue_nsn_build=True,
        organization_id=4,
    )

    assert result["inserted"] == 1
    assert result["part_finder_enrichment"]["processed"] == 1
    assert calls == [([88], 4, True, 1)]


def test_part_finder_vendor_seed_candidates_merge_provider_and_awardee():
    result = {
        "part": {
            "nsn": "6515-01-646-2617",
            "part_numbers": ["ABC-123"],
        },
        "providers": [
            {
                "name": "Acme Medical",
                "cage": "1ABC2",
                "roles": ["Approved Source"],
                "sources": ["PUB LOG"],
                "confidence": 88,
            }
        ],
        "awardees": [
            {
                "name": "Acme Medical",
                "cage": "1ABC2",
                "award_count": 3,
                "total_award_amount": 12500,
                "latest_award_date": "2025-01-03",
            }
        ],
    }

    candidates = _build_part_finder_candidates(result)

    assert len(candidates) == 1
    assert candidates[0]["source_type"] == "PART_FINDER_PROVIDER_AWARDEE"
    assert candidates[0]["company_name"] == "Acme Medical"
    assert candidates[0]["cage"] == "1ABC2"
    assert candidates[0]["part_number"] == "ABC-123"
    assert candidates[0]["is_approved_source"] is True


def test_part_finder_quote_seed_creates_quote_for_high_confidence_cage_lead():
    lead = SimpleNamespace(
        id=12,
        opportunity_id=77,
        organization_id=4,
        source_type="PART_FINDER_PROVIDER_AWARDEE",
        company_name="Acme Medical",
        cage="1ABC2",
        part_number="ABC-123",
        nsn="6515-01-646-2617",
        status="NEW",
        confidence=91,
        is_approved_source=True,
        notes="Provider and awardee evidence.",
        raw_text=None,
        updated_at=None,
    )
    provider = SimpleNamespace(
        id=31,
        organization_id=4,
        company_name="Acme Medical Official",
        cage="1ABC2",
        contact_name="Jane Buyer",
        email="quotes@acme.test",
        phone="555-0101",
        website="https://acme.test",
        updated_at=datetime(2026, 4, 19),
    )
    added = []

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, value):
            return self

        def all(self):
            return [lead] if self.model is VendorLead else []

        def first(self):
            if self.model is Provider:
                return provider
            return None

    class FakeDB:
        def query(self, model):
            return FakeQuery(model)

        def add(self, item):
            added.append(item)

        def flush(self):
            for index, item in enumerate(added, start=100):
                item.id = index

        def commit(self):
            self.committed = True

    result = seed_quotes_from_part_finder_leads(
        FakeDB(),
        SimpleNamespace(id=77, organization_id=4),
        organization_id=4,
    )

    assert result["created"] == 1
    assert result["seeded"][0]["quote_id"] == 100
    assert added[0].cage == "1ABC2"
    assert added[0].part_number == "ABC-123"
    assert added[0].status == "NOT_REQUESTED"
    assert added[0].contact_name == "Jane Buyer"
    assert added[0].email == "quotes@acme.test"
    assert added[0].phone == "555-0101"
    assert "Website: https://acme.test" in added[0].notes
    assert lead.status == "SEEDED_TO_QUOTES"


def test_part_finder_quote_seed_creates_email_draft(monkeypatch):
    quote = SimpleNamespace(
        id=100,
        opportunity_id=77,
        company_name="Acme Medical",
        cage="1ABC2",
        email="quotes@acme.test",
    )
    artifacts = []

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [] if self.model is WorkspaceArtifact else []

        def first(self):
            return quote if self.model is VendorQuote else None

    class FakeDB:
        def query(self, model):
            return FakeQuery(model)

        def rollback(self):
            self.rolled_back = True

    monkeypatch.setattr(
        part_vendor_leads,
        "generate_quote_request_email",
        lambda opportunity_id, db, vendor_quote_id: {
            "to": "quotes@acme.test",
            "company_name": "Acme Medical",
            "subject": "Quote Request",
            "body": "Please quote.",
        },
    )

    def fake_create_artifact(db, opp_id, artifact_type, title, content_json=None, **kwargs):
        artifact = SimpleNamespace(id=501, content_json=content_json, title=title)
        artifacts.append(artifact)
        return artifact

    monkeypatch.setattr(part_vendor_leads, "create_artifact", fake_create_artifact)

    result = create_email_drafts_for_part_finder_quotes(
        FakeDB(),
        SimpleNamespace(id=77),
        {"seeded": [{"quote_id": 100}]},
    )

    assert result["created"] == 1
    assert result["drafts"][0]["artifact_id"] == 501
    assert artifacts[0].content_json["vendor_quote_id"] == 100
    assert artifacts[0].content_json["generated_from"] == "part_finder_quote_auto_outreach"
    assert artifacts[0].content_json["_meta"]["artifact_subtype"] == "PART_FINDER_QUOTE_EMAIL"


def test_outreach_artifact_sent_updates_linked_quote_status():
    quote = SimpleNamespace(
        id=100,
        opportunity_id=77,
        organization_id=4,
        status="NOT_REQUESTED",
        requested_at=None,
        last_follow_up_at=None,
        next_follow_up_at=None,
        notes=None,
        updated_at=None,
    )
    artifact = SimpleNamespace(
        id=501,
        opportunity_id=77,
        content_json={"vendor_quote_id": 100},
    )
    added = []

    class FakeQuery:
        def filter(self, *args):
            return self

        def first(self):
            return quote

    class FakeDB:
        def query(self, model):
            assert model is VendorQuote
            return FakeQuery()

        def add(self, rec):
            added.append(rec)

    result = sync_quote_status_from_outreach_artifact(
        FakeDB(),
        artifact,
        "sent",
        organization_id=4,
    )

    assert result["updated"] is True
    assert result["vendor_quote_id"] == 100
    assert quote.status == "REQUESTED"
    assert quote.requested_at is not None
    assert quote.next_follow_up_at is not None
    assert "workspace artifact 501" in quote.notes
    assert added == [quote]


def test_outreach_artifact_draft_does_not_update_quote_status():
    artifact = SimpleNamespace(
        id=501,
        opportunity_id=77,
        content_json={"vendor_quote_id": 100},
    )

    class FakeDB:
        def query(self, model):
            raise AssertionError("draft actions should not query quotes")

    result = sync_quote_status_from_outreach_artifact(
        FakeDB(),
        artifact,
        "draft_saved",
        organization_id=4,
    )

    assert result == {"updated": False, "reason": "action_not_sent"}


def test_add_business_days_skips_weekends():
    start = datetime(2026, 4, 17, 10, 0, 0)

    result = add_business_days(start, 2)

    assert result.date().isoformat() == "2026-04-21"


def test_mark_quote_followed_up_reschedules_requested_quote():
    quote = SimpleNamespace(
        id=100,
        opportunity_id=77,
        organization_id=4,
        status="REQUESTED",
        requested_at=datetime(2026, 4, 17, 10, 0, 0),
        last_follow_up_at=None,
        next_follow_up_at=datetime(2026, 4, 21, 10, 0, 0),
        follow_up_count=0,
        notes=None,
        updated_at=None,
    )
    added = []

    class FakeQuery:
        def filter(self, *args):
            return self

        def first(self):
            return quote

    class FakeDB:
        def query(self, model):
            assert model is VendorQuote
            return FakeQuery()

        def add(self, rec):
            added.append(rec)

        def commit(self):
            pass

        def refresh(self, rec):
            pass

    result = mark_quote_followed_up(
        FakeDB(),
        opportunity_id=77,
        quote_id=100,
        organization_id=4,
        notes="Called supplier, awaiting price.",
    )

    assert result["vendor_quote_id"] == 100
    assert result["follow_up_count"] == 1
    assert quote.last_follow_up_at is not None
    assert quote.next_follow_up_at is not None
    assert quote.next_follow_up_at > quote.last_follow_up_at
    assert "Called supplier" in quote.notes
    assert added == [quote]


def test_quote_follow_up_summary_counts_due_and_scheduled_quotes():
    now = datetime(2026, 4, 22, 12, 0, 0)
    quotes = [
        SimpleNamespace(id=1, status="REQUESTED", next_follow_up_at=datetime(2026, 4, 22, 9, 0, 0)),
        SimpleNamespace(id=2, status="REQUESTED", next_follow_up_at=datetime(2026, 4, 24, 9, 0, 0)),
        SimpleNamespace(id=3, status="REQUESTED", next_follow_up_at=None),
        SimpleNamespace(id=4, status="RECEIVED", next_follow_up_at=None),
        SimpleNamespace(id=5, status="NOT_REQUESTED", next_follow_up_at=None),
    ]

    summary = build_quote_follow_up_summary(quotes, now=now)

    assert summary["total"] == 5
    assert summary["requested"] == 3
    assert summary["due"] == 1
    assert summary["scheduled"] == 1
    assert summary["missing_schedule"] == 1
    assert summary["closed"] == 1
    assert summary["not_requested"] == 1
    assert summary["due_quote_ids"] == [1]
    assert summary["next_due_at"] == datetime(2026, 4, 24, 9, 0, 0)
