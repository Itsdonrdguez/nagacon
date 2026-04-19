from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_db
from app.repositories.providers import ProviderRepository
from app.models.opportunity import Opportunity
from app.schemas.provider import (
    ProviderCreate,
    ProviderImportRequest,
    ProviderImportResult,
    ProviderOut,
    ProviderPdfExtractResult,
    ProviderRowOut,
    ProviderUpdate,
)
from app.services.providers.pdf_cage_extractor import (
    backfill_dibbs_provider_item_nomenclature,
    enrich_provider_websites_from_sam,
    extract_providers_from_dibbs_pdfs,
    extract_providers_from_opportunity_pdfs,
)
from app.services.providers.contact_discovery import discover_provider_contacts
from app.services.providers.identity_resolver import resolve_provider_identities

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _repo(db: Session, current_org) -> ProviderRepository:
    return ProviderRepository(db, organization_id=getattr(current_org, "id", None))


@router.get("")
def list_providers(
    q: str | None = None,
    nsn: str | None = None,
    fsc: str | None = None,
    relationship_type: str | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    rows, total = _repo(db, current_org).list_rows(
        q=q,
        nsn=nsn,
        fsc=fsc,
        relationship_type=relationship_type,
        source=source,
        limit=max(min(limit, 250), 1),
        offset=max(offset, 0),
    )
    return {
        "items": [ProviderRowOut(**row).model_dump() for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", response_model=ProviderOut)
def create_provider(
    payload: ProviderCreate,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return _repo(db, current_org).create(payload)


@router.patch("/{provider_id}", response_model=ProviderOut)
def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    provider = _repo(db, current_org).update(provider_id, payload)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.post("/import-csv", response_model=ProviderImportResult)
def import_providers_csv(
    payload: ProviderImportRequest = Body(...),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return _repo(db, current_org).import_csv(payload.content)


@router.post("/seed/vendor-leads", response_model=ProviderImportResult)
def seed_from_vendor_leads(
    limit: int = 500,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return _repo(db, current_org).seed_from_vendor_leads(limit=limit)


@router.post("/extract/dibbs-pdfs", response_model=ProviderPdfExtractResult)
def extract_from_dibbs_pdfs(
    enrich_with_sam: bool = True,
    limit: int | None = None,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return extract_providers_from_dibbs_pdfs(
        db,
        organization_id=getattr(current_org, "id", None),
        enrich_with_sam=enrich_with_sam,
        limit=limit,
    )


@router.post("/backfill/dibbs-nomenclature")
def backfill_dibbs_nomenclature(
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return backfill_dibbs_provider_item_nomenclature(
        db,
        organization_id=getattr(current_org, "id", None),
    )


@router.post("/enrich/sam-websites")
def enrich_sam_websites(
    limit: int = 250,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return enrich_provider_websites_from_sam(
        db,
        organization_id=getattr(current_org, "id", None),
        limit=limit,
    )


@router.post("/discover-contacts")
def discover_contacts(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return discover_provider_contacts(
        db,
        organization_id=getattr(current_org, "id", None),
        limit=limit,
    )


@router.post("/resolve-identities")
def resolve_identities(
    limit: int = 250,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    return resolve_provider_identities(
        db,
        organization_id=getattr(current_org, "id", None),
        limit=limit,
    )


@router.post("/extract/opportunity/{opportunity_id}", response_model=ProviderPdfExtractResult)
def extract_from_opportunity_pdfs(
    opportunity_id: int,
    enrich_with_sam: bool = True,
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
):
    org_id = getattr(current_org, "id", None)
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if org_id is not None:
        query = query.filter(Opportunity.organization_id == org_id)
    opp = query.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return extract_providers_from_opportunity_pdfs(
        db,
        opp,
        enrich_with_sam=enrich_with_sam,
        organization_id=org_id,
    )
