from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnAwardEvidence, NsnMaster, NsnReference
from app.repositories.providers import ProviderRepository
from app.schemas.provider import ProviderCreate, ProviderImportResult, ProviderItemCreate
from app.services.nsn_catalog.normalizer import normalize_nsn


def catalog_reference_role(reference: NsnReference) -> str:
    text = " ".join(
        str(value or "")
        for value in [
            reference.reference_type,
            reference.relationship_type,
            reference.source_name,
        ]
    ).lower()
    if any(token in text for token in ["approved", "source", "mcrl", "mcrd", "manufacturer", "mfr", "oem"]):
        return "OEM Candidate"
    if any(token in text for token in ["substitute", "interchange", "alternate"]):
        return "Alternate Source Candidate"
    return "Catalog Reference"


def catalog_reference_confidence(reference: NsnReference) -> float:
    score = 70.0
    if reference.cage:
        score += 10
    if reference.part_number:
        score += 10
    if reference.company_name:
        score += 5
    if (reference.source_name or "").upper() in {"PUB_LOG", "FLIS", "MCRD"}:
        score += 5
    if reference.confidence is not None:
        if reference.confidence <= 1:
            score = max(score, reference.confidence * 100)
        else:
            score = max(score, reference.confidence)
    return min(score, 95.0)


def provider_payload_from_reference(reference: NsnReference, item_name: str | None = None) -> ProviderCreate | None:
    company_name = (reference.company_name or "").strip()
    if not company_name and reference.cage:
        company_name = f"CAGE {reference.cage}"
    if not company_name:
        return None

    notes = []
    if reference.part_number:
        notes.append(f"Part number: {reference.part_number}")
    if reference.reference_type:
        notes.append(f"Reference type: {reference.reference_type}")
    if reference.relationship_type:
        notes.append(f"Catalog relationship: {reference.relationship_type}")
    if reference.source_version:
        notes.append(f"Source version: {reference.source_version}")

    return ProviderCreate(
        company_name=company_name,
        cage=reference.cage,
        notes=f"Seeded from {reference.source_name} catalog reference.",
        item=ProviderItemCreate(
            nsn=reference.nsn,
            fsc=reference.fsc,
            nomenclature=item_name,
            relationship_type=catalog_reference_role(reference),
            source=reference.source_name or "PUB LOG",
            confidence=catalog_reference_confidence(reference),
            notes="; ".join(notes) if notes else None,
        ),
    )


def provider_payload_from_award_evidence(row: NsnAwardEvidence, item_name: str | None = None) -> ProviderCreate | None:
    company_name = (row.recipient_name or "").strip()
    if not company_name and row.recipient_cage:
        company_name = f"CAGE {row.recipient_cage}"
    if not company_name:
        return None

    role = "Confirmed Awardee" if (row.match_confidence or "").lower() == "high" else "Likely Awardee"
    confidence = 95.0 if role == "Confirmed Awardee" else 82.0
    notes = []
    if row.award_id:
        notes.append(f"Award ID: {row.award_id}")
    if row.piid:
        notes.append(f"PIID: {row.piid}")
    if row.award_date:
        notes.append(f"Award date: {row.award_date}")
    if row.award_amount is not None:
        notes.append(f"Award amount: {row.award_amount}")
    if row.match_reasons:
        notes.append(f"Match reasons: {', '.join(row.match_reasons[:6])}")

    return ProviderCreate(
        company_name=company_name,
        cage=row.recipient_cage,
        uei=row.recipient_uei,
        notes=f"Seeded from {row.source_system} NSN award evidence.",
        item=ProviderItemCreate(
            nsn=row.nsn,
            fsc=row.fsc or row.psc_code,
            nomenclature=item_name,
            relationship_type=role,
            source=row.source_system or "USAspending",
            source_url=row.award_id or row.piid,
            confidence=confidence,
            notes="; ".join(notes) if notes else None,
        ),
    )


def seed_providers_from_nsn_catalog(
    db: Session,
    nsn: str,
    *,
    organization_id: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {
            "status": "invalid_nsn",
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["NSN must contain exactly 13 digits."],
        }

    master = db.query(NsnMaster).filter(NsnMaster.compact_nsn == target.compact).first()
    item_name = getattr(master, "item_name", None)
    references = (
        db.query(NsnReference)
        .filter(NsnReference.compact_nsn == target.compact)
        .filter((NsnReference.cage.is_not(None)) | (NsnReference.company_name.is_not(None)))
        .order_by(NsnReference.confidence.desc().nullslast(), NsnReference.company_name.asc().nullslast(), NsnReference.cage.asc().nullslast())
        .limit(max(min(limit, 1000), 1))
        .all()
    )

    repo = ProviderRepository(db, organization_id=organization_id)
    result = ProviderImportResult()
    seeded: list[dict[str, Any]] = []

    for reference in references:
        payload = provider_payload_from_reference(reference, item_name=item_name)
        if not payload:
            result.skipped += 1
            continue
        try:
            existing = repo._find_provider(company_name=payload.company_name, cage=payload.cage, uei=None)
            provider = repo.create(payload)
            if existing:
                result.updated += 1
            else:
                result.inserted += 1
            seeded.append(
                {
                    "provider_id": provider.id,
                    "company_name": provider.company_name,
                    "cage": provider.cage,
                    "relationship_type": payload.item.relationship_type if payload.item else None,
                    "source": payload.item.source if payload.item else None,
                    "confidence": payload.item.confidence if payload.item else None,
                }
            )
        except Exception as exc:
            db.rollback()
            result.errors.append(f"{reference.cage or reference.company_name or reference.id}: {exc}")

    return result.model_dump() | {
        "status": "ok",
        "nsn": target.nsn,
        "references_checked": len(references),
        "seeded": seeded,
    }


def seed_providers_from_nsn_award_evidence(
    db: Session,
    nsn: str,
    *,
    organization_id: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {
            "status": "invalid_nsn",
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["NSN must contain exactly 13 digits."],
        }

    master = db.query(NsnMaster).filter(NsnMaster.compact_nsn == target.compact).first()
    item_name = getattr(master, "item_name", None)
    rows = (
        db.query(NsnAwardEvidence)
        .filter(NsnAwardEvidence.compact_nsn == target.compact)
        .filter(NsnAwardEvidence.match_confidence.in_(["high", "medium"]))
        .order_by(NsnAwardEvidence.match_score.desc().nullslast(), NsnAwardEvidence.award_date.desc().nullslast())
        .limit(max(min(limit, 1000), 1))
        .all()
    )

    repo = ProviderRepository(db, organization_id=organization_id)
    result = ProviderImportResult()
    seeded: list[dict[str, Any]] = []
    for row in rows:
        payload = provider_payload_from_award_evidence(row, item_name=item_name)
        if not payload:
            result.skipped += 1
            continue
        try:
            existing = repo._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
            provider = repo.create(payload)
            if existing:
                result.updated += 1
            else:
                result.inserted += 1
            seeded.append(
                {
                    "provider_id": provider.id,
                    "company_name": provider.company_name,
                    "cage": provider.cage,
                    "relationship_type": payload.item.relationship_type if payload.item else None,
                    "source": payload.item.source if payload.item else None,
                    "confidence": payload.item.confidence if payload.item else None,
                }
            )
        except Exception as exc:
            db.rollback()
            result.errors.append(f"{row.recipient_cage or row.recipient_name or row.id}: {exc}")

    return result.model_dump() | {
        "status": "ok",
        "nsn": target.nsn,
        "award_rows_checked": len(rows),
        "seeded": seeded,
    }
