from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.opportunity import Opportunity
from app.repositories.providers import ProviderRepository
from app.schemas.provider import ProviderCreate, ProviderItemCreate
from app.services.intelligence.nsn_intelligence_service import build_nsn_research_target, run_nsn_intelligence
from app.services.nsn_catalog.build import build_nsn_intelligence
from app.services.providers.identity_resolver import resolve_provider_identities


def award_followup_status(opp: Opportunity, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.utcnow()
    due_at = getattr(opp, "due_at", None)
    confirmed_count = (
        getattr(opp, "_award_history_count", None)
        if hasattr(opp, "_award_history_count")
        else None
    )
    if due_at is None or due_at >= current:
        return {
            "status": "ACTIVE_RFQ",
            "days_since_close": None,
            "award_expected_after": due_at + timedelta(days=90) if due_at else None,
            "follow_up_eligible": False,
        }
    days = max((current - due_at).days, 0)
    expected_after = due_at + timedelta(days=90)
    status = "READY_FOR_USASPENDING_CHECK" if current >= expected_after else "AWAITING_USASPENDING"
    if confirmed_count:
        status = "USASPENDING_CONFIRMED"
    return {
        "status": status,
        "days_since_close": days,
        "award_expected_after": expected_after,
        "follow_up_eligible": status == "READY_FOR_USASPENDING_CHECK",
    }


def enrich_awardees_for_opportunity(
    db: Session,
    opportunity_id: int,
    *,
    organization_id: int | None = None,
    force: bool = False,
    progress_callback=None,
) -> dict[str, Any]:
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if organization_id is not None:
        query = query.filter(Opportunity.organization_id == organization_id)
    opp = query.first()
    if not opp:
        return {"status": "not_found", "error": "Opportunity not found"}

    existing_awards = db.query(AwardHistory).filter(AwardHistory.opportunity_id == opp.id).count()
    setattr(opp, "_award_history_count", existing_awards)
    followup = award_followup_status(opp)
    target = build_nsn_research_target(db, opp)
    _emit(progress_callback, "target", "Resolved opportunity NSN/FSC target", 1, 5)

    nsn_build = None
    if target.get("nsn"):
        nsn_build = build_nsn_intelligence(
            db,
            target["nsn"],
            run_usaspending=bool(force or followup["follow_up_eligible"]),
            seed_providers=True,
            organization_id=getattr(opp, "organization_id", None),
            limit=50,
            progress_callback=lambda event: _emit_nested(progress_callback, event, 2, 5),
        )
    _emit(progress_callback, "candidate_sources", "Seeded candidate providers from catalog evidence", 2, 5)

    intelligence = None
    if force or followup["follow_up_eligible"]:
        intelligence = run_nsn_intelligence(db, opp, seed_awardees=True, create_summary_artifact=True)
    _emit(progress_callback, "award_check", "Checked official award evidence when eligible", 3, 5)

    promoted = _promote_award_history_to_providers(db, opp)
    _emit(progress_callback, "awardees", "Promoted confirmed awardees into provider roles", 4, 5)

    identities = resolve_provider_identities(db, organization_id=getattr(opp, "organization_id", None), limit=500)
    _emit(progress_callback, "identity", "Resolved provider identity evidence", 5, 5)

    return {
        "status": "ok",
        "opportunity_id": opp.id,
        "solicitation_number": opp.solicitation_number,
        "award_followup": _json_dates(followup),
        "target": target,
        "nsn_build": nsn_build,
        "nsn_intelligence": intelligence,
        "promoted_awardees": promoted,
        "identity_resolution": identities,
    }


def _promote_award_history_to_providers(db: Session, opp: Opportunity) -> dict[str, Any]:
    rows = (
        db.query(AwardHistory)
        .filter(AwardHistory.opportunity_id == opp.id, AwardHistory.match_confidence != "weak")
        .order_by(AwardHistory.match_score.desc().nullslast())
        .limit(50)
        .all()
    )
    repo = ProviderRepository(db, organization_id=getattr(opp, "organization_id", None))
    promoted = 0
    for row in rows:
        if not row.recipient_name and not row.recipient_cage:
            continue
        provider = repo.create(
            ProviderCreate(
                company_name=row.recipient_name or f"CAGE {row.recipient_cage}",
                cage=row.recipient_cage,
                uei=row.recipient_uei,
                notes=f"Confirmed awardee evidence from {row.source_system}: {row.award_id or row.piid or 'award record'}",
                item=ProviderItemCreate(
                    nsn=row.nsn,
                    fsc=row.fsc or row.psc_code,
                    relationship_type="Confirmed Awardee",
                    source=row.source_system,
                    source_url=row.award_id or row.piid,
                    confidence=95 if row.match_confidence in {"exact", "strong"} else 80,
                    notes=f"Award date: {row.award_date}; amount: {row.award_amount}; matched by {', '.join(row.match_reasons or [])}",
                ),
            )
        )
        promoted += int(bool(provider))
    return {"promoted": promoted, "award_rows": len(rows)}


def _emit(callback, source: str, label: str, completed_steps: int, total_steps: int) -> None:
    if callback:
        callback({"source": source, "label": label, "completed_steps": completed_steps, "total_steps": total_steps})


def _emit_nested(callback, event: dict[str, Any], completed_steps: int, total_steps: int) -> None:
    if callback:
        callback(
            {
                "source": event.get("source") or "nsn_build",
                "label": event.get("label") or "Building NSN intelligence",
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            }
        )


def _json_dates(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in payload.items()}
