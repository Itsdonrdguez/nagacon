from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.dibbs.detail_enrichment_playwright import enrich_dibbs_batch

router = APIRouter(prefix="/api/dibbs", tags=["dibbs"])


@router.post("/enrich-playwright")
def enrich(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    limit = int(payload.get("limit") or 10)
    source = str(payload.get("source") or "DIBBS")
    debug = bool(payload.get("debug") or False)
    return enrich_dibbs_batch(db=db, limit=limit, source=source, debug=debug)
