from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.vendor import VendorLead


APPROVED_SOURCE_TYPES = {"DIBBS_APPROVED_SOURCE"}
SUPPRESSIBLE_SOURCE_TYPES = {"USASPENDING_AWARD_HISTORY"}


def suppress_non_dibbs_leads_for_opportunity(
    db: Session,
    opportunity_id: int,
    suppressible_source_types: set[str] | None = None,
) -> dict[str, Any]:
    suppressible = suppressible_source_types or SUPPRESSIBLE_SOURCE_TYPES

    approved_count = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opportunity_id)
        .filter(VendorLead.source_type.in_(list(APPROVED_SOURCE_TYPES)))
        .count()
    )

    if approved_count == 0:
        return {
            "ok": True,
            "opportunity_id": opportunity_id,
            "suppressed_count": 0,
            "suppressed_ids": [],
            "message": "No DIBBS approved-source leads found. Nothing suppressed.",
        }

    rows = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opportunity_id)
        .filter(VendorLead.source_type.in_(list(suppressible)))
        .all()
    )

    suppressed_ids: list[int] = []

    for row in rows:
        row.status = "SUPPRESSED"
        notes = (row.notes or "").strip()
        suppress_note = "Suppressed because DIBBS approved source exists for this opportunity"
        if suppress_note not in notes:
            row.notes = f"{notes}; {suppress_note}" if notes else suppress_note
        db.add(row)
        suppressed_ids.append(row.id)

    db.commit()

    return {
        "ok": True,
        "opportunity_id": opportunity_id,
        "approved_source_count": approved_count,
        "suppressed_count": len(suppressed_ids),
        "suppressed_ids": suppressed_ids,
    }


def auto_suppress_non_dibbs_leads_if_approved_exists(db: Session, opportunity_id: int) -> dict[str, Any]:
    return suppress_non_dibbs_leads_for_opportunity(db=db, opportunity_id=opportunity_id)
