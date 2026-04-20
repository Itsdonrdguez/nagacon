from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead


def seed_vendor_leads_from_part_finder_result(
    db: Session,
    opp: Opportunity,
    result: dict[str, Any],
    *,
    organization_id: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    candidates = _build_part_finder_candidates(result, limit=limit)
    created = 0
    updated = 0
    skipped = 0
    seeded: list[dict[str, Any]] = []

    for candidate in candidates:
        if not candidate.get("company_name") and not candidate.get("cage"):
            skipped += 1
            continue
        rec = _find_existing_lead(db, opp.id, candidate)
        if rec:
            if _update_lead(rec, candidate, organization_id=organization_id or getattr(opp, "organization_id", None)):
                updated += 1
            seeded.append(_lead_seed_payload(rec, "updated"))
            continue

        rec = VendorLead(
            organization_id=organization_id or getattr(opp, "organization_id", None),
            opportunity_id=opp.id,
            source_type=candidate["source_type"],
            company_name=candidate.get("company_name"),
            cage=candidate.get("cage"),
            part_number=candidate.get("part_number"),
            nsn=candidate.get("nsn"),
            status="NEW",
            confidence=candidate.get("confidence") or 60,
            is_approved_source=bool(candidate.get("is_approved_source")),
            raw_text=candidate.get("raw_text"),
            notes=candidate.get("notes"),
        )
        db.add(rec)
        db.flush()
        created += 1
        seeded.append(_lead_seed_payload(rec, "created"))

    if created or updated:
        db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "candidate_count": len(candidates),
        "seeded": seeded,
    }


def _build_part_finder_candidates(result: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    part = result.get("part") or {}
    nsn = _clean(part.get("nsn"))
    first_part_number = _first(part.get("part_numbers") or [])
    candidates: dict[tuple[str, str | None], dict[str, Any]] = {}

    def merge_candidate(row: dict[str, Any]) -> None:
        company_name = _clean(row.get("company_name"), 200)
        cage = _clean(row.get("cage"), 10)
        part_number = _clean(row.get("part_number"), 80)
        if not company_name and not cage:
            return
        key = ((cage or company_name or "").upper(), part_number)
        item = candidates.setdefault(
            key,
            {
                "company_name": company_name,
                "cage": cage,
                "part_number": part_number,
                "nsn": nsn,
                "confidence": 0,
                "is_approved_source": False,
                "evidence_types": set(),
                "notes_parts": [],
                "raw_parts": [],
            },
        )
        if company_name and not item.get("company_name"):
            item["company_name"] = company_name
        item["confidence"] = max(int(item.get("confidence") or 0), int(row.get("confidence") or 0))
        item["is_approved_source"] = bool(item.get("is_approved_source") or row.get("is_approved_source"))
        if row.get("evidence_type"):
            item["evidence_types"].add(row["evidence_type"])
        if row.get("notes"):
            item["notes_parts"].append(row["notes"])
        if row.get("raw_text"):
            item["raw_parts"].append(row["raw_text"])

    for provider in (result.get("providers") or [])[:limit]:
        roles = [str(role) for role in (provider.get("roles") or []) if role]
        sources = [str(source) for source in (provider.get("sources") or []) if source]
        role_text = ", ".join(roles) or "Provider"
        is_approved = any("approved" in role.lower() for role in roles) or any("approved" in source.lower() for source in sources)
        merge_candidate(
            {
                "company_name": provider.get("name"),
                "cage": provider.get("cage"),
                "part_number": first_part_number,
                "confidence": _provider_confidence(provider, is_approved=is_approved),
                "is_approved_source": is_approved,
                "evidence_type": "PART_FINDER_PROVIDER",
                "notes": f"Part Finder provider candidate. Roles: {role_text}. Sources: {', '.join(sources) or 'NSN catalog/provider evidence'}.",
                "raw_text": f"Part Finder provider for NSN {nsn}; roles={roles}; sources={sources}",
            }
        )

    for awardee in (result.get("awardees") or [])[:limit]:
        award_count = int(awardee.get("award_count") or 0)
        amount = awardee.get("total_award_amount") or 0
        merge_candidate(
            {
                "company_name": awardee.get("name"),
                "cage": awardee.get("cage"),
                "part_number": first_part_number,
                "confidence": min(92, 62 + min(award_count * 6, 24)),
                "is_approved_source": False,
                "evidence_type": "PART_FINDER_AWARDEE",
                "notes": (
                    "Part Finder awardee evidence. "
                    f"Award count: {award_count}. Total amount: {amount}. "
                    f"Latest award: {_clean(awardee.get('latest_award_date')) or 'not reported'}."
                ),
                "raw_text": f"Part Finder awardee for NSN {nsn}; sources={awardee.get('sources') or []}",
            }
        )

    output: list[dict[str, Any]] = []
    for item in candidates.values():
        evidence_types = sorted(item.pop("evidence_types"))
        notes_parts = _unique(item.pop("notes_parts"))
        raw_parts = _unique(item.pop("raw_parts"))
        item["source_type"] = _source_type_from_evidence(evidence_types)
        item["notes"] = " ".join(notes_parts)[:4000] or None
        item["raw_text"] = " | ".join(raw_parts)[:4000] or None
        output.append(item)

    return sorted(output, key=lambda row: (-(row.get("confidence") or 0), row.get("company_name") or row.get("cage") or ""))[:limit]


def _find_existing_lead(db: Session, opportunity_id: int, candidate: dict[str, Any]) -> VendorLead | None:
    cage = candidate.get("cage")
    company_name = candidate.get("company_name")
    part_number = candidate.get("part_number")
    query = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)
    if cage:
        query = query.filter(func.upper(func.coalesce(VendorLead.cage, "")) == cage.upper())
    else:
        query = query.filter(VendorLead.cage.is_(None))
        if company_name:
            query = query.filter(func.lower(func.coalesce(VendorLead.company_name, "")) == company_name.lower())
    if part_number:
        query = query.filter(VendorLead.part_number == part_number)
    else:
        query = query.filter(VendorLead.part_number.is_(None))
    return query.first()


def _update_lead(rec: VendorLead, candidate: dict[str, Any], *, organization_id: int | None = None) -> bool:
    touched = False
    for attr in ["company_name", "cage", "part_number", "nsn"]:
        value = candidate.get(attr)
        if value and not getattr(rec, attr, None):
            setattr(rec, attr, value)
            touched = True
    if organization_id is not None and rec.organization_id is None:
        rec.organization_id = organization_id
        touched = True
    if candidate.get("confidence") and int(candidate["confidence"]) > int(rec.confidence or 0):
        rec.confidence = int(candidate["confidence"])
        touched = True
    if candidate.get("is_approved_source") and not rec.is_approved_source:
        rec.is_approved_source = True
        touched = True
    source_type = _combine_source_types(rec.source_type, candidate.get("source_type"))
    if source_type != rec.source_type:
        rec.source_type = source_type
        touched = True
    notes = _merge_text(rec.notes, candidate.get("notes"))
    if notes != rec.notes:
        rec.notes = notes
        touched = True
    raw_text = _merge_text(rec.raw_text, candidate.get("raw_text"))
    if raw_text != rec.raw_text:
        rec.raw_text = raw_text
        touched = True
    if touched:
        rec.updated_at = datetime.utcnow()
    return touched


def _source_type_from_evidence(evidence_types: list[str]) -> str:
    if "PART_FINDER_PROVIDER" in evidence_types and "PART_FINDER_AWARDEE" in evidence_types:
        return "PART_FINDER_PROVIDER_AWARDEE"
    if "PART_FINDER_AWARDEE" in evidence_types:
        return "PART_FINDER_AWARDEE"
    return "PART_FINDER_PROVIDER"


def _combine_source_types(left: str | None, right: str | None) -> str:
    values = {item for item in [left, right] if item}
    if {"PART_FINDER_PROVIDER", "PART_FINDER_AWARDEE"}.issubset(values) or "PART_FINDER_PROVIDER_AWARDEE" in values:
        values.discard("PART_FINDER_PROVIDER")
        values.discard("PART_FINDER_AWARDEE")
        values.add("PART_FINDER_PROVIDER_AWARDEE")
    return "+".join(sorted(values)) if values else "PART_FINDER_PROVIDER"


def _provider_confidence(provider: dict[str, Any], *, is_approved: bool) -> int:
    try:
        raw = int(float(provider.get("confidence") or 0))
    except (TypeError, ValueError):
        raw = 0
    if raw <= 0:
        raw = 78 if provider.get("cage") else 68
    if is_approved:
        raw += 8
    return min(max(raw, 55), 98)


def _lead_seed_payload(rec: VendorLead, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "lead_id": rec.id,
        "company_name": rec.company_name,
        "cage": rec.cage,
        "source_type": rec.source_type,
        "confidence": rec.confidence,
    }


def _merge_text(current: str | None, incoming: str | None, *, max_len: int = 4000) -> str | None:
    current_clean = _clean(current)
    incoming_clean = _clean(incoming)
    if not incoming_clean:
        return current_clean
    if not current_clean:
        return incoming_clean[:max_len]
    if incoming_clean.lower() in current_clean.lower():
        return current_clean
    return f"{current_clean} {incoming_clean}"[:max_len]


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _first(values: list[Any]) -> str | None:
    for value in values:
        text = _clean(value, 80)
        if text:
            return text
    return None


def _clean(value: Any, max_len: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_len] if max_len else text
