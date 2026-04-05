from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.opportunity import RawOpportunity
from app.services.opportunity_ingest import upsert_raw_opportunity
from app.services.scrapers.dibbs_scraper import fetch_dibbs_opportunities
from app.services.scrapers.sam_scraper import SamScraperError, fetch_sam_opportunities
from app.services.scrapers.state_local_scraper import (
    fetch_dc_opportunities,
    fetch_eva_opportunities,
    fetch_maryland_opportunities,
)

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"])


def _ingest_many(db: Session, raw_opps: list[RawOpportunity]) -> dict[str, Any]:
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for raw in raw_opps:
        try:
            result = upsert_raw_opportunity(db, raw, force_refresh=True)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(str(exc))

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/sam/run")
def run_sam_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    try:
        raw_opps = fetch_sam_opportunities(payload or {})
        out = _ingest_many(db, raw_opps)
        if (payload or {}).get("debug"):
            out["diagnostics"] = {
                "request": payload or {},
                "rows_parsed": len(raw_opps),
                "source": "sam.gov",
            }
        return out
    except SamScraperError as exc:
        return {
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [str(exc)],
            "diagnostics": {"request": payload or {}, "rows_parsed": 0, "source": "sam.gov"},
        }


@router.post("/dibbs/run")
def run_dibbs_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.get("max_pages") or 1)
    raw_opps = fetch_dibbs_opportunities(params=payload, max_pages=max_pages)
    out = _ingest_many(db, raw_opps)
    if payload.get("debug"):
        out["diagnostics"] = {
            "request_fsc": payload.get("fsc") or payload.get("fsc_code"),
            "request_limit": int(payload.get("limit") or payload.get("page_size") or 25),
            "pages_fetched": max_pages,
            "rows_parsed": len(raw_opps),
            "mode": "adapter",
        }
    return out


@router.post("/state-local/eva/run")
def run_eva_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.pop("max_pages", 2))
    return _ingest_many(db, fetch_eva_opportunities(params=payload, max_pages=max_pages))


@router.post("/state-local/maryland/run")
def run_maryland_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.pop("max_pages", 2))
    return _ingest_many(db, fetch_maryland_opportunities(params=payload, max_pages=max_pages))


@router.post("/state-local/dc/run")
def run_dc_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.pop("max_pages", 2))
    return _ingest_many(db, fetch_dc_opportunities(params=payload, max_pages=max_pages))


@router.post("/state-local/all/run")
def run_all_state_local(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})

    eva_params = dict(payload)
    md_params = dict(payload)
    dc_params = dict(payload)

    result = {}
    try:
        result["eva"] = _ingest_many(db, fetch_eva_opportunities(params=eva_params, max_pages=int(eva_params.pop("max_pages", 2))))
    except Exception as exc:
        result["eva"] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}
    try:
        result["maryland"] = _ingest_many(db, fetch_maryland_opportunities(params=md_params, max_pages=int(md_params.pop("max_pages", 2))))
    except Exception as exc:
        result["maryland"] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}
    try:
        result["dc"] = _ingest_many(db, fetch_dc_opportunities(params=dc_params, max_pages=int(dc_params.pop("max_pages", 2))))
    except Exception as exc:
        result["dc"] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}

    return result
