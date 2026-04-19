from __future__ import annotations

from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.repositories.company import CompanyRepository
from app.schemas.company import (
    CompanyProfileCreate,
    CompanyProfileOut,
    CompanyProfileUpdate,
    PastPerformanceCreate,
    PastPerformanceOut,
    PastPerformanceUpdate,
)
from app.services.company_profile_ingest import build_company_ingest_plan, run_company_profile_ingest

router = APIRouter(prefix="/api/company", tags=["company"])


@router.post("/profile", response_model=CompanyProfileOut)
def create_profile(item: CompanyProfileCreate, db: Session = Depends(get_db)):
    return CompanyRepository(db).create_profile(item)


@router.get("/profile/{profile_id}", response_model=CompanyProfileOut)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    rec = CompanyRepository(db).get_profile(profile_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return rec


@router.get("/profile", response_model=CompanyProfileOut | None)
def get_first_profile(db: Session = Depends(get_db)):
    return CompanyRepository(db).get_first_profile()


@router.patch("/profile/{profile_id}", response_model=CompanyProfileOut)
def update_profile(profile_id: int, item: CompanyProfileUpdate, db: Session = Depends(get_db)):
    rec = CompanyRepository(db).update_profile(profile_id, item)
    if not rec:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return rec


@router.get("/ingest-plan")
def get_profile_ingest_plan(db: Session = Depends(get_db)):
    profile = CompanyRepository(db).get_first_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return build_company_ingest_plan(profile)


@router.post("/ingest-run")
def run_profile_ingest(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    profile = CompanyRepository(db).get_first_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Company profile not found")
    quick = bool((payload or {}).get("quick", False))
    return run_company_profile_ingest(db, profile, quick=quick, update_last_run=not quick)


@router.post("/past-performance", response_model=PastPerformanceOut)
def create_past_performance(item: PastPerformanceCreate, db: Session = Depends(get_db)):
    return CompanyRepository(db).create_past_performance(item)


@router.get("/past-performance/{profile_id}", response_model=List[PastPerformanceOut])
def list_past_performance(profile_id: int, db: Session = Depends(get_db)):
    return CompanyRepository(db).list_past_performance(profile_id)


@router.patch("/past-performance/{perf_id}", response_model=PastPerformanceOut)
def update_past_performance(perf_id: int, item: PastPerformanceUpdate, db: Session = Depends(get_db)):
    rec = CompanyRepository(db).update_past_performance(perf_id, item)
    if not rec:
        raise HTTPException(status_code=404, detail="Past performance record not found")
    return rec
