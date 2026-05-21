from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.deps import get_current_organization, get_current_user
from app.services.vendors.usaspending import find_similar_awardees

router = APIRouter(
    prefix="/api/vendors/usaspending",
    tags=["vendors", "usaspending"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


class USAspendingVendorSearchRequest(BaseModel):
    naics_code: str | None = None
    keywords: list[str] = Field(default_factory=list)
    awarding_agency: str | None = None
    page: int = 1
    limit: int = 10


@router.post("/search")
def search_usaspending_vendors(req: USAspendingVendorSearchRequest) -> dict[str, Any]:
    try:
        return find_similar_awardees(
            naics_code=req.naics_code,
            keywords=req.keywords,
            awarding_agency=req.awarding_agency,
            page=req.page,
            limit=req.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"USAspending vendor search failed: {exc}")
