from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CompanyProfileBase(BaseModel):
    legal_name: str
    uei: Optional[str] = None
    cage: Optional[str] = None
    naics_codes: Optional[List[str]] = None
    certifications: Optional[List[str]] = None
    capability_statement_url: Optional[str] = None
    core_competencies: Optional[str] = None
    differentiators: Optional[str] = None
    past_performance_summary: Optional[str] = None
    annual_revenue: Optional[float] = Field(default=None, ge=0)


class CompanyProfileCreate(CompanyProfileBase):
    pass


class CompanyProfileUpdate(BaseModel):
    legal_name: Optional[str] = None
    uei: Optional[str] = None
    cage: Optional[str] = None
    naics_codes: Optional[List[str]] = None
    certifications: Optional[List[str]] = None
    capability_statement_url: Optional[str] = None
    core_competencies: Optional[str] = None
    differentiators: Optional[str] = None
    past_performance_summary: Optional[str] = None
    annual_revenue: Optional[float] = Field(default=None, ge=0)


class CompanyProfileOut(CompanyProfileBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PastPerformanceBase(BaseModel):
    client_name: str
    project_title: str
    project_value: Optional[float] = Field(default=None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: Optional[str] = None
    naics_code: Optional[str] = None
    relevance_tags: Optional[List[str]] = None


class PastPerformanceCreate(PastPerformanceBase):
    company_profile_id: int


class PastPerformanceUpdate(BaseModel):
    client_name: Optional[str] = None
    project_title: Optional[str] = None
    project_value: Optional[float] = Field(default=None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: Optional[str] = None
    naics_code: Optional[str] = None
    relevance_tags: Optional[List[str]] = None


class PastPerformanceOut(PastPerformanceBase):
    id: int
    company_profile_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
