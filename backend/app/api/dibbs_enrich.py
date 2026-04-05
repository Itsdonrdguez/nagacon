from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.opportunity import Opportunity
from app.services.dibbs.detail_enrichment_playwright import enrich_dibbs_batch
from app.services.dibbs.approved_source_leads import seed_vendor_leads_from_dibbs_approved_sources

router = APIRouter(prefix="/api/dibbs", tags=["dibbs"])


@router.post("/enrich")
def enrich(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    return enrich_dibbs_batch(
        db=db,
        limit=int(payload.get("limit", 10)),
        source=str(payload.get("source", "DIBBS")),
        debug=bool(payload.get("debug", False)),
        auto_seed_approved_sources=bool(payload.get("auto_seed_approved_sources", True)),
    )


@router.post("/enrich-playwright")
def enrich_playwright(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    return enrich_dibbs_batch(
        db=db,
        limit=int(payload.get("limit", 10)),
        source=str(payload.get("source", "DIBBS")),
        debug=bool(payload.get("debug", False)),
        auto_seed_approved_sources=bool(payload.get("auto_seed_approved_sources", True)),
    )


@router.post("/pipeline")
def pipeline(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    return enrich_dibbs_batch(
        db=db,
        limit=int(payload.get("limit", 10)),
        source=str(payload.get("source", "DIBBS")),
        debug=bool(payload.get("debug", False)),
        auto_seed_approved_sources=True,
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
