from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.opportunity import Opportunity
from app.services.dibbs.detail_enrichment_playwright import enrich_dibbs_batch
from app.services.dibbs.approved_source_leads import seed_vendor_leads_from_dibbs_approved_sources
from app.services.import_run_service import complete_import_run, start_import_run

router = APIRouter(
    prefix="/api/dibbs",
    tags=["dibbs"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


def _parse_dibbs_date(value: str | None):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _run_dibbs_enrichment(
    payload: dict,
    db: Session,
    *,
    organization_id: int | None,
    user_id: int | None,
    source_label: str,
):
    run = start_import_run(
        db,
        source=source_label,
        run_kind="dibbs_enrichment",
        request_payload=payload,
        organization_id=organization_id,
        user_id=user_id,
    )
    try:
        result = enrich_dibbs_batch(
            db=db,
            limit=int(payload.get("limit", 10)),
            source=str(payload.get("source", "DIBBS")),
            debug=bool(payload.get("debug", False)),
            auto_seed_approved_sources=bool(payload.get("auto_seed_approved_sources", True)),
        )
        complete_import_run(
            db,
            run,
            status="completed" if not int(result.get("failed") or 0) else "partial_success",
            result_payload=result,
            row_count=int(result.get("requested_limit") or 0),
            updated_count=int(result.get("enriched") or 0),
            skipped_count=int(result.get("failed") or 0),
        )
        return result
    except Exception as exc:
        complete_import_run(db, run, status="failed", error_message=str(exc))
        raise


@router.post("/enrich")
def enrich(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    return _run_dibbs_enrichment(
        payload,
        db,
        organization_id=getattr(current_org, "id", None),
        user_id=getattr(current_user, "id", None),
        source_label="DIBBS_ENRICHMENT",
    )


@router.post("/enrich-playwright")
def enrich_playwright(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    return _run_dibbs_enrichment(
        payload,
        db,
        organization_id=getattr(current_org, "id", None),
        user_id=getattr(current_user, "id", None),
        source_label="DIBBS_ENRICHMENT_PLAYWRIGHT",
    )


@router.post("/pipeline")
def pipeline(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    merged_payload = {**dict(payload or {}), "auto_seed_approved_sources": True}
    return _run_dibbs_enrichment(
        merged_payload,
        db,
        organization_id=getattr(current_org, "id", None),
        user_id=getattr(current_user, "id", None),
        source_label="DIBBS_PIPELINE",
    )


@router.post("/approved-sources/seed")
def seed_approved_sources(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    opportunity_id = payload.get("opportunity_id")
    if not opportunity_id:
        return {"ok": False, "error": "opportunity_id is required"}
    return seed_vendor_leads_from_dibbs_approved_sources(db=db, opportunity_id=int(opportunity_id))


@router.post("/cleanup-junk")
def cleanup_junk(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    source = str(payload.get("source", "DIBBS"))
    preview = bool(payload.get("preview", True))

    rows = db.query(Opportunity).filter(Opportunity.source == source).all()
    junk_ids = []

    for opp in rows:
        url = (getattr(opp, "url", None) or "").upper()
        sol = (getattr(opp, "solicitation_number", None) or "").upper()
        title = (getattr(opp, "title", None) or "").upper()

        is_junk = (
            "RFQDATES.ASPX" in url
            or "DEFAULT.ASPX" in url
            or "RECENT RFQS" in sol
            or "RFQS BY ISSUE DATE" in sol
            or "RFQS BY RETURN BY DATE" in sol
            or title in {"RECENT RFQS", "RFQ SEARCH", "RFQS", "RFQS BY ISSUE DATE", "RFQS BY RETURN BY DATE"}
        )
        if is_junk:
            junk_ids.append(opp.id)

    if preview:
        return {"ok": True, "preview": True, "junk_count": len(junk_ids), "junk_ids": junk_ids}

    deleted = 0
    for opp_id in junk_ids:
        row = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
        if row:
            db.delete(row)
            deleted += 1
    db.commit()

    return {"ok": True, "preview": False, "deleted": deleted, "junk_ids": junk_ids}


@router.post("/backfill-dates")
def backfill_dibbs_dates(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    limit = int(payload.get("limit", 1000))
    preview = bool(payload.get("preview", False))

    rows = (
        db.query(Opportunity)
        .filter(Opportunity.source == "DIBBS")
        .order_by(Opportunity.id.desc())
        .limit(limit)
        .all()
    )

    scanned = 0
    updated_due = 0
    updated_posted = 0
    touched_ids: list[int] = []

    for opp in rows:
        scanned += 1
        raw_payload = getattr(opp, "raw_payload", None) or {}
        if not isinstance(raw_payload, dict):
            continue
        dibbs_detail = raw_payload.get("dibbs_detail") or {}
        if not isinstance(dibbs_detail, dict):
            continue
        structured = dibbs_detail.get("structured") if isinstance(dibbs_detail.get("structured"), dict) else dibbs_detail
        solicitations = structured.get("solicitations") or []
        first = solicitations[0] if solicitations else {}
        if not isinstance(first, dict):
            continue

        due_at = _parse_dibbs_date(first.get("return_by_date"))
        posted_at = _parse_dibbs_date(first.get("issue_date"))
        changed = False

        if due_at is not None and getattr(opp, "due_at", None) is None:
            updated_due += 1
            changed = True
            if not preview:
                opp.due_at = due_at

        if posted_at is not None and getattr(opp, "posted_at", None) is None:
            updated_posted += 1
            changed = True
            if not preview:
                opp.posted_at = posted_at

        if changed:
            touched_ids.append(opp.id)

    if not preview and touched_ids:
        db.commit()

    return {
        "ok": True,
        "preview": preview,
        "scanned": scanned,
        "updated_due_at": updated_due,
        "updated_posted_at": updated_posted,
        "touched_ids": touched_ids[:100],
        "touched_count": len(touched_ids),
    }
