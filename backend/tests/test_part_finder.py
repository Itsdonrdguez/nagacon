from types import SimpleNamespace

from app.schemas.opportunity import RawOpportunity
from app.services.part_vendor_leads import _build_part_finder_candidates
from app.services.part_finder import _target_from_opportunity, find_parts_batch


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
