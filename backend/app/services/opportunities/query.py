from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.repositories.opportunities import OpportunityRepository
from app.repositories.pipeline import PipelineRepository
from app.repositories.quotes import QuoteRepository
from app.repositories.vendor_matches import VendorMatchRepository


def get_opportunity_workspace(opp_id: int, db: Session) -> Optional[Dict]:
    opp_repo = OpportunityRepository(db)
    opp = opp_repo.get(opp_id)
    if not opp:
        return None

    pipeline_item = PipelineRepository(db).get_by_opportunity_id(opp_id)
    vendor_matches = VendorMatchRepository(db).list_by_opportunity_id(opp_id)
    quotes = QuoteRepository(db).list_by_opportunity_id(opp_id)

    documents = []
    agent_runs = []

    return {
        "opportunity": opp,
        "pipeline_item": pipeline_item,
        "documents": documents,
        "vendor_matches": vendor_matches,
        "quotes": quotes,
        "agent_runs": agent_runs,
    }
