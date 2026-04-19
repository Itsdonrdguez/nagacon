from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProviderItemBase(BaseModel):
    nsn: Optional[str] = None
    fsc: Optional[str] = None
    nomenclature: Optional[str] = None
    relationship_type: str = "Unknown"
    source: str = "Manual"
    source_url: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None


class ProviderItemCreate(ProviderItemBase):
    pass


class ProviderItemOut(ProviderItemBase):
    id: int
    provider_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProviderBase(BaseModel):
    company_name: str
    cage: Optional[str] = None
    uei: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    status: str = "active"
    canonical_name: Optional[str] = None
    identity_source: Optional[str] = None
    identity_confidence: Optional[float] = None
    aliases: list[str] = Field(default_factory=list)


class ProviderCreate(ProviderBase):
    item: Optional[ProviderItemCreate] = None


class ProviderUpdate(BaseModel):
    company_name: Optional[str] = None
    cage: Optional[str] = None
    uei: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ProviderOut(ProviderBase):
    id: int
    organization_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    items: list[ProviderItemOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ProviderRowOut(BaseModel):
    provider_id: int
    provider_item_id: Optional[int] = None
    company_name: str
    cage: Optional[str] = None
    uei: Optional[str] = None
    website: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    provider_notes: Optional[str] = None
    status: str
    canonical_name: Optional[str] = None
    identity_source: Optional[str] = None
    identity_confidence: Optional[float] = None
    aliases: list[str] = Field(default_factory=list)
    nsn: Optional[str] = None
    fsc: Optional[str] = None
    nomenclature: Optional[str] = None
    relationship_type: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    confidence: Optional[float] = None
    item_notes: Optional[str] = None
    item_count: int = 0
    relationship_types: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    nsns: list[str] = Field(default_factory=list)
    fscs: list[str] = Field(default_factory=list)
    item_summaries: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class ProviderImportRequest(BaseModel):
    content: str


class ProviderImportResult(BaseModel):
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class ProviderPdfExtractResult(ProviderImportResult):
    scanned_files: int = 0
    valid_pdfs: int = 0
    invalid_pdfs: int = 0
    cages_found: int = 0
    sam_enriched: int = 0
    sam_misses: int = 0
    vendor_leads_created: int = 0
    vendor_leads_updated: int = 0
    providers_matched: int = 0
