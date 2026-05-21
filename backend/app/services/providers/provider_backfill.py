from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.nsn_catalog import NsnAwardEvidence
from app.models.provider import Provider
from app.repositories.providers import ProviderRepository
from app.schemas.provider import ProviderCreate, ProviderItemCreate
from app.services.nsn_catalog.provider_seeding import provider_payload_from_award_evidence
from app.services.providers.identity_resolver import resolve_provider_identity
from app.services.providers.pdf_cage_extractor import enrich_provider_websites_from_sam


def run_provider_backfill(
    db: Session,
    *,
    organization_id: int | None = None,
    limit: int = 250,
    enrich_websites: bool = True,
    user_id: int | None = None,
    progress_callback=None,
) -> dict[str, Any]:
    repo = ProviderRepository(db, organization_id=organization_id)
    total_steps = 4

    _emit(progress_callback, "providers", "Collecting unresolved providers", 1, total_steps)
    unresolved = _unresolved_providers(db, organization_id=organization_id, limit=limit)

    resolved = 0
    for provider in unresolved:
        result = resolve_provider_identity(db, provider)
        resolved += int(bool(result))
    if unresolved:
        db.commit()

    _emit(progress_callback, "providers", "Promoting award evidence into providers", 2, total_steps)
    award_seed = _seed_from_nsn_award_evidence(db, repo, organization_id=organization_id, limit=limit)

    _emit(progress_callback, "providers", "Promoting opportunity award history into providers", 3, total_steps)
    history_seed = _seed_from_award_history(db, repo, organization_id=organization_id, limit=limit)

    _emit(progress_callback, "providers", "Enriching provider websites and identities", 4, total_steps)
    website_result = (
        enrich_provider_websites_from_sam(db, organization_id=organization_id, user_id=user_id, limit=limit)
        if enrich_websites
        else {"checked": 0, "updated": 0, "missing_api_key": False, "errors": []}
    )
    resolve_provider_identities = 0
    post_seed = _unresolved_providers(db, organization_id=organization_id, limit=limit)
    for provider in post_seed:
        result = resolve_provider_identity(db, provider)
        resolve_provider_identities += int(bool(result))
    if post_seed:
        db.commit()

    return {
        "status": "ok",
        "organization_id": organization_id,
        "unresolved_checked": len(unresolved),
        "identities_resolved": resolved + resolve_provider_identities,
        "nsn_award_provider_seed": award_seed,
        "award_history_provider_seed": history_seed,
        "website_enrichment": website_result,
    }


def _unresolved_providers(db: Session, *, organization_id: int | None, limit: int) -> list[Provider]:
    query = db.query(Provider)
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)
    query = query.filter(
        or_(
            Provider.company_name.ilike("CAGE %"),
            Provider.company_name.in_(["Solicitations", "Solicitation", "Unknown Provider"]),
            Provider.canonical_name.is_(None),
        )
    )
    return query.order_by(Provider.updated_at.desc(), Provider.id.desc()).limit(max(min(limit, 1000), 1)).all()


def _seed_from_nsn_award_evidence(
    db: Session,
    repo: ProviderRepository,
    *,
    organization_id: int | None,
    limit: int,
) -> dict[str, Any]:
    rows = (
        db.query(NsnAwardEvidence)
        .filter(NsnAwardEvidence.match_confidence.in_(["high", "medium"]))
        .order_by(NsnAwardEvidence.match_score.desc().nullslast(), NsnAwardEvidence.award_date.desc().nullslast())
        .limit(max(min(limit, 1000), 1))
        .all()
    )
    inserted = 0
    updated = 0
    skipped = 0
    for row in rows:
        payload = provider_payload_from_award_evidence(row)
        if not payload:
            skipped += 1
            continue
        existing = repo._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
        repo.create(payload)
        if existing:
            updated += 1
        else:
            inserted += 1
    return {"checked": len(rows), "inserted": inserted, "updated": updated, "skipped": skipped}


def _seed_from_award_history(
    db: Session,
    repo: ProviderRepository,
    *,
    organization_id: int | None,
    limit: int,
) -> dict[str, Any]:
    query = db.query(AwardHistory).filter(AwardHistory.match_confidence.in_(["high", "medium", "strong", "exact"]))
    if organization_id is not None:
        query = query.filter(or_(AwardHistory.organization_id == organization_id, AwardHistory.organization_id.is_(None)))
    rows = (
        query.order_by(AwardHistory.match_score.desc().nullslast(), AwardHistory.award_date.desc().nullslast())
        .limit(max(min(limit, 1000), 1))
        .all()
    )
    inserted = 0
    updated = 0
    skipped = 0
    for row in rows:
        company_name = (row.recipient_name or "").strip() or (f"CAGE {row.recipient_cage}" if row.recipient_cage else "")
        if not company_name:
            skipped += 1
            continue
        payload = ProviderCreate(
            company_name=company_name,
            cage=row.recipient_cage,
            uei=row.recipient_uei,
            notes=f"Backfilled from {row.source_system} award history.",
            item=ProviderItemCreate(
                nsn=row.nsn,
                fsc=row.fsc or row.psc_code,
                relationship_type="Confirmed Awardee" if str(row.match_confidence).lower() in {"high", "strong", "exact"} else "Likely Awardee",
                source=row.source_system or "Award History",
                source_url=row.award_id or row.piid,
                confidence=92.0 if str(row.match_confidence).lower() in {"high", "strong", "exact"} else 80.0,
                notes=f"Award date: {row.award_date}; amount: {row.award_amount}; matched by {', '.join(row.match_reasons or [])}",
            ),
        )
        existing = repo._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
        repo.create(payload)
        if existing:
            updated += 1
        else:
            inserted += 1
    return {"checked": len(rows), "inserted": inserted, "updated": updated, "skipped": skipped}


def _emit(callback, source: str, label: str, completed_steps: int, total_steps: int) -> None:
    if callback:
        callback(
            {
                "source": source,
                "label": label,
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            }
        )
