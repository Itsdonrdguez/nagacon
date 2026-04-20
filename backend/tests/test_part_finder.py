from types import SimpleNamespace

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
