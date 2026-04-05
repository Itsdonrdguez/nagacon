
from typing import Optional
from rapidfuzz import fuzz
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.repositories.opportunities import OpportunityRepository

DUPE_TITLE_THRESHOLD = 90


def find_potential_duplicate(db: Session, opp: OpportunityCreate, exclude_id: Optional[int] = None) -> Optional[int]:
    repo = OpportunityRepository(db)
    recent_cutoff = datetime.utcnow() - timedelta(days=30)

    query = db.query(Opportunity).filter(
        Opportunity.source == opp.source,
        Opportunity.created_at >= recent_cutoff
    )

    if exclude_id:
        query = query.filter(Opportunity.id != exclude_id)

    candidates = query.limit(100).all()

    for cand in candidates:
        if not cand.title or not opp.title:
            continue

        score = fuzz.ratio(cand.title.lower(), opp.title.lower())

        if score >= DUPE_TITLE_THRESHOLD and (cand.agency == opp.agency or cand.url == opp.url):
            return cand.id

    return None


def merge_into_existing(existing: Opportunity, new_data: OpportunityCreate) -> OpportunityUpdate:
    return OpportunityUpdate(**new_data.model_dump())
