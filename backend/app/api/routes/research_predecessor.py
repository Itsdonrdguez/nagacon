from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.research.predecessor_history import find_predecessor_opportunities

router = APIRouter(prefix="/api/research/predecessor", tags=["research"])


@router.get("/opportunities/{opportunity_id}")
def predecessor_history(opportunity_id: int, db: Session = Depends(get_db)):
    predecessors = find_predecessor_opportunities(db, opportunity_id)
    return {
        "opportunity_id": opportunity_id,
        "predecessor_count": len(predecessors),
        "predecessors": predecessors,
    }
