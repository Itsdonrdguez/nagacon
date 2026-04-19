from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead


def _lead_exists(db: Session, opportunity_id: int, cage: str | None, part_number: str | None, company_name: str | None) -> VendorLead | None:
    q = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)

    if cage:
        found = q.filter(VendorLead.cage == cage).first()
        if found:
            return found

    if company_name and part_number:
        found = (
            db.query(VendorLead)
            .filter(VendorLead.opportunity_id == opportunity_id)
            .filter(VendorLead.company_name == company_name)
            .filter(VendorLead.part_number == part_number)
            .first()
        )
        if found:
            return found

    return None


def _confidence_from_source(source: dict[str, Any]) -> int:
    cage = bool(source.get("cage"))
    part_number = bool(source.get("part_number"))
    company_name = bool(source.get("company_name"))

    score = 80
    if cage:
        score += 10
    if part_number:
        score += 5
    if company_name:
        score += 5
    return min(score, 99)


def seed_vendor_leads_from_dibbs_approved_sources(db: Session, opportunity_id: int) -> dict[str, Any]:
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        return {"ok": False, "error": f"Opportunity {opportunity_id} not found"}

    raw_payload = getattr(opportunity, "raw_payload", None) or {}
    dibbs_detail = raw_payload.get("dibbs_detail") or {}
    approved_sources = dibbs_detail.get("approved_sources") or []

    if not approved_sources:
        return {
            "ok": True,
            "opportunity_id": opportunity_id,
            "created": 0,
            "updated": 0,
            "seeded_count": 0,
            "seeded": [],
            "source": "DIBBS_APPROVED_SOURCE",
            "message": "No approved sources found in raw_payload.dibbs_detail.approved_sources",
        }

    created = 0
    updated = 0
    seeded: list[dict[str, Any]] = []

    nsn = dibbs_detail.get("nsn")
    fsc = dibbs_detail.get("fsc_code")
    solicitation_number = getattr(opportunity, "solicitation_number", None)
    title = getattr(opportunity, "title", None)

    for src in approved_sources:
        cage = (src.get("cage") or None)
        part_number = (src.get("part_number") or None)
        company_name = (src.get("company_name") or None)

        existing = _lead_exists(db, opportunity_id, cage, part_number, company_name)
        confidence = _confidence_from_source(src)

        note_bits = ["Seeded from DIBBS approved source"]
        if solicitation_number:
            note_bits.append(f"solicitation={solicitation_number}")
        if title:
            note_bits.append(f"title={title}")
        if nsn:
            note_bits.append(f"nsn={nsn}")
        if fsc:
            note_bits.append(f"fsc={fsc}")

        notes = "; ".join(note_bits)

        if existing:
            if existing.organization_id is None and getattr(opportunity, "organization_id", None) is not None:
                existing.organization_id = getattr(opportunity, "organization_id", None)
            existing.source_type = "DIBBS_APPROVED_SOURCE"
            existing.company_name = company_name or existing.company_name
            existing.cage = cage or existing.cage
            existing.part_number = part_number or existing.part_number
            existing.nsn = nsn or existing.nsn
            existing.status = getattr(existing, "status", None) or "NEW"
            existing.confidence = max(getattr(existing, "confidence", 0) or 0, confidence)
            existing.is_approved_source = True
            existing.raw_text = f"DIBBS approved source for {solicitation_number or opportunity_id}"
            existing.notes = notes
            db.add(existing)
            updated += 1
        else:
            lead = VendorLead(
                organization_id=getattr(opportunity, "organization_id", None),
                opportunity_id=opportunity_id,
                source_type="DIBBS_APPROVED_SOURCE",
                company_name=company_name,
                cage=cage,
                part_number=part_number,
                nsn=nsn,
                status="NEW",
                confidence=confidence,
                is_approved_source=True,
                raw_text=f"DIBBS approved source for {solicitation_number or opportunity_id}",
                notes=notes,
            )
            db.add(lead)
            created += 1

        seeded.append(
            {
                "company_name": company_name,
                "cage": cage,
                "part_number": part_number,
                "nsn": nsn,
                "confidence": confidence,
            }
        )

    db.commit()

    return {
        "ok": True,
        "opportunity_id": opportunity_id,
        "created": created,
        "updated": updated,
        "seeded_count": len(seeded),
        "seeded": seeded,
        "source": "DIBBS_APPROVED_SOURCE",
    }
