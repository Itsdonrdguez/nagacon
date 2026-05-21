from pathlib import Path
from types import SimpleNamespace

from app.services.nsn_catalog.normalizer import normalize_nsn
from app.services.nsn_catalog.catalog_service import _alternate_graph
from app.services.nsn_catalog.publog_decomp import _resolve_related_nsn_candidates
from app.services.nsn_catalog.publog_importer import parse_publog_csv, parse_publog_row
from app.services.nsn_catalog.provider_seeding import (
    catalog_reference_confidence,
    catalog_reference_role,
    provider_payload_from_award_evidence,
    provider_payload_from_reference,
)
from app.services.nsn_catalog.vendor_recommendations import build_vendor_recommendations
from app.services.research.usaspending_research_service import (
    _classify_award,
    _expand_context_with_catalog,
    _query_plan,
    search_usaspending_for_nsn,
)
from app.services.nsn_catalog.refresh import refresh_nsn_intelligence


TEST_TEMP_DIR = Path(__file__).resolve().parent / "_tmp"


def test_normalize_nsn_formats_compact_value():
    parsed = normalize_nsn("4110015342682")

    assert parsed is not None
    assert parsed.nsn == "4110-01-534-2682"
    assert parsed.compact == "4110015342682"
    assert parsed.fsc == "4110"
    assert parsed.niin == "015342682"


def test_parse_publog_row_accepts_full_nsn_and_reference_fields():
    row = parse_publog_row(
        {
            "National Stock Number": "4110-01-534-2682",
            "Item Name": "REFRIGERATION UNIT",
            "CAGE Code": "1abc2",
            "Reference Number": "PN-123",
            "Manufacturer Name": "Acme Defense",
            "RNCC": "3",
        }
    )

    assert row is not None
    assert row.nsn == "4110-01-534-2682"
    assert row.item_name == "REFRIGERATION UNIT"
    assert row.cage == "1ABC2"
    assert row.part_number == "PN-123"
    assert row.company_name == "Acme Defense"
    assert row.reference_type == "3"


def test_parse_publog_row_builds_nsn_from_fsc_and_niin():
    row = parse_publog_row(
        {
            "FSC": "4110",
            "NIIN": "015342682",
            "Nomenclature": "REFRIGERATION UNIT",
        }
    )

    assert row is not None
    assert row.nsn == "4110-01-534-2682"
    assert row.item_name == "REFRIGERATION UNIT"


def test_parse_publog_csv_handles_interchangeability_headers():
    TEST_TEMP_DIR.mkdir(exist_ok=True)
    csv_path = TEST_TEMP_DIR / "mdis.csv"
    csv_path.write_text(
        "NSN,Related NSN,Relationship Type,Order Of Use\n"
        "4110015342682,4110011234567,substitute,1\n",
        encoding="utf-8",
    )

    rows = parse_publog_csv(csv_path)

    assert len(rows) == 1
    assert rows[0].nsn == "4110-01-534-2682"
    assert rows[0].related_nsn == "4110-01-123-4567"
    assert rows[0].relationship_type == "substitute"
    assert rows[0].order_of_use == "1"


def test_resolve_related_nsn_candidates_maps_related_inc_to_actual_nsns():
    rows = _resolve_related_nsn_candidates(
        "6515016462617",
        [{"RELATED_INC": "35972", "ITEM_NAME": "TEST KIT,THEOPHYLLINE DETERMINAT"}],
        {
            "35972": [
                {"FSC": "6550", "NIIN": "014856112", "INC": "35972", "ITEM_NAME": "TEST KIT,THEOPHYLLINE DETERMINAT"},
                {"FSC": "6550", "NIIN": "014858613", "INC": "35972", "ITEM_NAME": "TEST KIT,THEOPHYLLINE DETERMINAT"},
            ]
        },
    )

    assert [row["related_nsn"] for row in rows] == [
        "6550-01-485-6112",
        "6550-01-485-8613",
    ]
    assert all(row["relationship_type"] == "related_item_concept_nsn" for row in rows)
    assert all(row["related_inc"] == "35972" for row in rows)


def test_provider_payload_from_catalog_reference_labels_oem_candidate():
    reference = SimpleNamespace(
        nsn="4110-01-534-2682",
        fsc="4110",
        cage="1ABC2",
        company_name="Acme Defense",
        part_number="PN-123",
        reference_type="MCRD",
        relationship_type="manufacturer",
        source_name="PUB_LOG",
        source_version="2026-04",
        confidence=0.9,
    )

    payload = provider_payload_from_reference(reference, item_name="REFRIGERATION UNIT")

    assert payload is not None
    assert payload.company_name == "Acme Defense"
    assert payload.cage == "1ABC2"
    assert payload.item is not None
    assert payload.item.nsn == "4110-01-534-2682"
    assert payload.item.nomenclature == "REFRIGERATION UNIT"
    assert payload.item.relationship_type == "OEM Candidate"
    assert payload.item.source == "PUB_LOG"
    assert payload.item.confidence == 95.0
    assert "PN-123" in payload.item.notes


def test_provider_payload_from_award_evidence_labels_confirmed_awardee():
    award = SimpleNamespace(
        recipient_name="Acme Defense LLC",
        recipient_cage="1ABC2",
        recipient_uei="UEI123",
        source_system="USAspending",
        nsn="4110-01-534-2682",
        fsc="4110",
        psc_code="4110",
        award_id="AWD-123",
        piid="PIID-456",
        award_date="2025-01-01",
        award_amount=12500,
        match_confidence="high",
        match_reasons=["part_number_match:PN-123", "catalog_manufacturer_match:acme defense"],
    )

    payload = provider_payload_from_award_evidence(award, item_name="REFRIGERATION UNIT")

    assert payload is not None
    assert payload.company_name == "Acme Defense LLC"
    assert payload.cage == "1ABC2"
    assert payload.item is not None
    assert payload.item.relationship_type == "Confirmed Awardee"
    assert payload.item.source == "USAspending"
    assert payload.item.confidence == 95.0
    assert "Award ID: AWD-123" in (payload.item.notes or "")


def test_catalog_reference_role_keeps_weak_reference_distinct():
    reference = SimpleNamespace(
        reference_type="unknown",
        relationship_type="cross reference",
        source_name="PUB_LOG",
        cage="1ABC2",
        part_number="PN-123",
        company_name=None,
        confidence=None,
    )

    assert catalog_reference_role(reference) == "Catalog Reference"
    assert catalog_reference_confidence(reference) == 95.0


def test_vendor_recommendations_merge_catalog_provider_award_and_price(monkeypatch):
    nsn = "4110-01-534-2682"
    reference = SimpleNamespace(
        company_name="Acme Defense",
        cage="1ABC2",
        part_number="PN-123",
        source_name="PUB_LOG",
        reference_type="MCRD",
        relationship_type="manufacturer",
        confidence=0.9,
    )
    provider = SimpleNamespace(id=7, company_name="Acme Defense", cage="1ABC2", website="https://acme.test")
    provider_item = SimpleNamespace(
        relationship_type="OEM Candidate",
        source="PUB_LOG",
        confidence=95,
        notes="Part number: PN-123",
    )
    award = SimpleNamespace(
        recipient_name="Acme Defense",
        recipient_cage="1ABC2",
        source_system="USAspending",
        award_id="AWD-1",
        piid="PIID-1",
        award_date="2025-01-01",
        award_amount=12000,
        match_confidence="high",
        match_reasons=["exact_nsn"],
        match_score=0.92,
    )
    price = SimpleNamespace(
        supplier_name="Acme Defense",
        cage="1ABC2",
        source_label="Price History",
        award_id="AWD-1",
        award_date="2025-01-01",
        quantity=4,
        unit_price=3000,
        total_price=12000,
        confidence=90,
    )

    monkeypatch.setattr(
        "app.services.nsn_catalog.vendor_recommendations._catalog_references",
        lambda db, compact: [reference],
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.vendor_recommendations._provider_rows",
        lambda db, value: [(provider, provider_item)],
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.vendor_recommendations._award_rows",
        lambda db, value: [award],
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.vendor_recommendations._nsn_award_rows",
        lambda db, compact: [],
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.vendor_recommendations._price_rows",
        lambda db, value: [price],
    )

    recommendations = build_vendor_recommendations(object(), nsn)

    assert len(recommendations) == 1
    candidate = recommendations[0]
    assert candidate["company_name"] == "Acme Defense"
    assert candidate["cage"] == "1ABC2"
    assert candidate["provider_id"] == 7
    assert candidate["confidence"] == "high"
    assert "OEM Candidate" in candidate["roles"]
    assert "Historical Awardee" in candidate["roles"]
    assert "Price History Supplier" in candidate["roles"]
    assert any(item["type"] == "catalog_reference" for item in candidate["evidence"])
    assert any(item["type"] == "award_history" for item in candidate["evidence"])


def test_alternate_graph_includes_named_related_nsns():
    graph = _alternate_graph(
        normalize_nsn("6515016462617"),
        references=[],
        interchangeability=[
            SimpleNamespace(
                related_nsn="6550-01-485-6112",
                related_compact_nsn="6550014856112",
                relationship_type="related_item_concept_nsn",
                notes="TEST KIT,THEOPHYLLINE DETERMINAT",
                source_name="PUB_LOG_V_H6_RELATED",
                confidence=0.72,
            )
        ],
        evidence=[],
        providers=[],
        vendor_recommendations=[],
        related_masters={
            "6550014856112": {
                "nsn": "6550-01-485-6112",
                "compact_nsn": "6550014856112",
                "item_name": "TEST KIT,THEOPHYLLINE DETERMINAT",
                "fsc": "6550",
            }
        },
    )

    assert graph["actual_related_nsn_count"] == 1
    assert graph["concept_only_count"] == 0
    assert graph["related_nodes"][0]["related_value"] == "6550-01-485-6112"
    assert graph["related_nodes"][0]["related_item_name"] == "TEST KIT,THEOPHYLLINE DETERMINAT"
    assert graph["related_nodes"][0]["related_fsc"] == "6550"


def test_usaspending_context_expands_with_catalog_references():
    ctx = {
        "nsn": "4110-01-534-2682",
        "fsc_code": "4110",
        "naics_code": "",
        "agency_variants": [],
        "keywords": ["refrigeration", "unit"],
        "keyword_variants": [["refrigeration", "unit"]],
        "part_numbers": [],
        "manufacturers": [],
        "approved_source_names": [],
        "approved_source_cages": [],
        "nomenclature": "",
    }
    catalog = {
        "catalog_item_name": "REFRIGERATION UNIT",
        "catalog_part_numbers": ["PN-123"],
        "catalog_manufacturers": ["Acme Defense"],
        "catalog_cages": ["1ABC2"],
        "catalog_reference_count": 1,
    }

    expanded = _expand_context_with_catalog(ctx, catalog)
    plans = _query_plan(expanded)
    labels = [plan["label"] for plan in plans]

    assert expanded["nsn_compact"] == "4110015342682"
    assert expanded["niin"] == "015342682"
    assert "PN-123" in expanded["part_numbers"]
    assert "Acme Defense" in expanded["manufacturers"]
    assert any(label.startswith("compact_nsn_only:") for label in labels)
    assert any(label.startswith("niin+psc:") for label in labels)
    assert any(label.startswith("part_number+psc:PN-123") for label in labels)


def test_usaspending_classification_uses_catalog_part_number_query_match():
    ctx = {
        "nsn": "4110-01-534-2682",
        "nsn_compact": "4110015342682",
        "niin": "015342682",
        "fsc_code": "4110",
        "part_numbers": ["PN-123"],
        "catalog_part_numbers": ["PN-123"],
        "manufacturers": ["Acme Defense"],
        "catalog_manufacturers": ["Acme Defense"],
        "approved_source_names": [],
        "keywords": ["refrigeration"],
        "catalog_reference_count": 1,
    }
    row = {
        "recipient_name": "Acme Defense",
        "description": "Purchase of refrigeration unit part PN-123 for DLA stock.",
        "matched_by": "part_number+psc:PN-123",
    }

    classified = _classify_award(row, ctx)

    assert classified["match_category"] == "product_like"
    assert classified["seedable_product_evidence"] is True
    assert classified["strict_seedable_product_evidence"] is True
    assert "part_number_match:PN-123" in classified["relevance_reasons"]
    assert "part_number_query_match:PN-123" in classified["relevance_reasons"]
    assert "catalog_part_number_evidence:PN-123" in classified["relevance_reasons"]


def test_search_usaspending_for_nsn_uses_standalone_context(monkeypatch):
    monkeypatch.setattr(
        "app.services.research.usaspending_research_service._catalog_context_for_nsn",
        lambda db, nsn: {
            "catalog_item_name": "REFRIGERATION UNIT",
            "catalog_part_numbers": ["PN-123"],
            "catalog_manufacturers": ["Acme Defense"],
            "catalog_cages": ["1ABC2"],
            "catalog_reference_count": 1,
        },
    )
    monkeypatch.setattr(
        "app.services.research.usaspending_research_service._call_usaspending",
        lambda payload: [],
    )

    result = search_usaspending_for_nsn(object(), "4110015342682", limit=5)
    labels = [run["label"] for run in result["query_debug"]]

    assert result["opportunity_id"] is None
    assert result["context"]["nsn"] == "4110-01-534-2682"
    assert result["context"]["catalog_item_name"] == "REFRIGERATION UNIT"
    assert any(label.startswith("compact_nsn_only:4110015342682") for label in labels)
    assert any(label.startswith("part_number+psc:PN-123") for label in labels)


def test_refresh_nsn_intelligence_stores_snapshot(monkeypatch):
    snapshots = []

    class FakeDB:
        def add(self, item):
            snapshots.append(item)

        def commit(self):
            snapshots[-1].id = 42

        def refresh(self, item):
            return None

    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.search_usaspending_for_nsn",
        lambda db, nsn, limit=50: {
            "history_match_source": "none",
            "history_match_label": "No USAspending history match",
            "history_match_query_label": None,
            "awards_found": 0,
            "awards": [],
            "product_like_awards": [],
            "seedable_product_like_awards": [],
            "strict_seedable_product_like_awards": [],
            "likely_vendors": [],
            "seedable_product_like_vendors": [],
            "query_debug": [],
        },
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.get_nsn_catalog_summary",
        lambda db, nsn: {
            "target": {"nsn": "4110-01-534-2682", "compact_nsn": "4110015342682"},
            "identity": {"status": "not_in_local_catalog"},
            "references": [],
            "interchangeability": [],
            "vendor_recommendations": [],
            "providers": [],
            "award_history": {"count": 0},
            "pricing": {"count": 0},
            "confidence": {"identity": "low"},
            "next_actions": ["Import or refresh PUB LOG catalog data for this NSN."],
        },
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.seed_providers_from_nsn_catalog",
        lambda db, nsn, organization_id=None, limit=50: {"status": "ok", "inserted": 1, "updated": 0},
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.seed_providers_from_nsn_award_evidence",
        lambda db, nsn, organization_id=None, limit=50: {"status": "ok", "inserted": 2, "updated": 1},
    )

    result = refresh_nsn_intelligence(FakeDB(), "4110015342682", run_usaspending=True, seed_providers=True)

    assert result["status"] == "ok"
    assert result["snapshot_id"] == 42
    assert result["nsn"] == "4110-01-534-2682"
    assert result["summary"]["usaspending"]["awards_found"] == 0
    assert result["summary"]["provider_seed"]["inserted"] == 1
    assert result["summary"]["award_provider_seed"]["inserted"] == 2
    assert result["confidence"]["award_providers_inserted"] == 2
    assert snapshots[0].compact_nsn == "4110015342682"
    assert snapshots[0].source_scope == "refresh"


def test_refresh_nsn_intelligence_handles_usaspending_timeout(monkeypatch):
    snapshots = []

    class FakeDB:
        def add(self, item):
            snapshots.append(item)

        def commit(self):
            snapshots[-1].id = 77

        def refresh(self, item):
            return None

    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.search_usaspending_for_nsn",
        lambda db, nsn, limit=50: (_ for _ in ()).throw(__import__("requests").exceptions.ConnectTimeout("timed out")),
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.get_nsn_catalog_summary",
        lambda db, nsn: {
            "target": {"nsn": "4110-01-534-2682", "compact_nsn": "4110015342682"},
            "identity": {"status": "not_in_local_catalog"},
            "references": [],
            "interchangeability": [],
            "vendor_recommendations": [],
            "providers": [],
            "award_history": {"count": 0},
            "pricing": {"count": 0},
            "confidence": {"identity": "low"},
            "next_actions": ["Import or refresh PUB LOG catalog data for this NSN."],
        },
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.seed_providers_from_nsn_catalog",
        lambda db, nsn, organization_id=None, limit=50: {"status": "ok", "inserted": 1, "updated": 0},
    )
    monkeypatch.setattr(
        "app.services.nsn_catalog.refresh.seed_providers_from_nsn_award_evidence",
        lambda db, nsn, organization_id=None, limit=50: {"status": "ok", "inserted": 0, "updated": 0},
    )

    result = __import__("app.services.nsn_catalog.refresh", fromlist=["refresh_nsn_intelligence"]).refresh_nsn_intelligence(
        FakeDB(),
        "4110015342682",
        run_usaspending=True,
        seed_providers=True,
    )

    assert result["status"] == "partial_success"
    assert result["snapshot_id"] == 77
    assert result["summary"]["usaspending"] is None
    assert "ConnectTimeout" in result["summary"]["usaspending_error"]
    assert result["errors"]
