from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.opportunities.ingest import ingest_raw_opportunities
from app.services.scrapers.dibbs_scraper import fetch_dibbs_opportunities
from app.services.scrapers.sam_scraper import fetch_sam_opportunities
from app.services.scrapers.state_local_scraper import (
    fetch_dc_opportunities,
    fetch_eva_opportunities,
    fetch_maryland_opportunities,
)

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"])


@router.post("/sam/run")
def run_sam_scraper(params: dict | None = None, db: Session = Depends(get_db)):
    raw_opps = fetch_sam_opportunities(params or {})
    return ingest_raw_opportunities(db, raw_opps)


@router.post("/dibbs/run")
def run_dibbs_scraper(params: dict | None = None, db: Session = Depends(get_db)):
    params = params or {}
    max_pages = int(params.pop("max_pages", 2))
    raw_opps = fetch_dibbs_opportunities(params=params, max_pages=max_pages)
    return ingest_raw_opportunities(db, raw_opps)


@router.post("/state-local/eva/run")
def run_eva_scraper(params: dict | None = None, db: Session = Depends(get_db)):
    params = params or {}
    max_pages = int(params.pop("max_pages", 2))
    raw_opps = fetch_eva_opportunities(params=params, max_pages=max_pages)
    return ingest_raw_opportunities(db, raw_opps)


@router.post("/state-local/maryland/run")
def run_maryland_scraper(params: dict | None = None, db: Session = Depends(get_db)):
    params = params or {}
    max_pages = int(params.pop("max_pages", 2))
    raw_opps = fetch_maryland_opportunities(params=params, max_pages=max_pages)
    return ingest_raw_opportunities(db, raw_opps)


@router.post("/state-local/dc/run")
def run_dc_scraper(params: dict | None = None, db: Session = Depends(get_db)):
    params = params or {}
    max_pages = int(params.pop("max_pages", 2))
    raw_opps = fetch_dc_opportunities(params=params, max_pages=max_pages)
    return ingest_raw_opportunities(db, raw_opps)


@router.post("/state-local/all/run")
def run_all_state_local(params: dict | None = None, db: Session = Depends(get_db)):
    params = params or {}
    eva_params = dict(params)
    md_params = dict(params)
    dc_params = dict(params)

    eva = ingest_raw_opportunities(db, fetch_eva_opportunities(eva_params, max_pages=int(eva_params.pop("max_pages", 2))))
    maryland = ingest_raw_opportunities(db, fetch_maryland_opportunities(md_params, max_pages=int(md_params.pop("max_pages", 2))))
    dc = ingest_raw_opportunities(db, fetch_dc_opportunities(dc_params, max_pages=int(dc_params.pop("max_pages", 2))))

    return {
        "eva": eva.model_dump() if hasattr(eva, "model_dump") else eva,
        "maryland": maryland.model_dump() if hasattr(maryland, "model_dump") else maryland,
        "dc": dc.model_dump() if hasattr(dc, "model_dump") else dc,
    }
