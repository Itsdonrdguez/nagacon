from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.opportunity import Opportunity
from app.services.research.usaspending_research_service import search_usaspending_for_opportunity
from app.services.provider_settings_service import get_effective_sam_api_key
from app.research.predecessor_history import find_predecessor_opportunities

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/")
def health_check(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    checks: dict[str, str] = {}
    opp_id = None

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "OK"
    except Exception as e:
        checks["database"] = f"ERROR: {e}"

    try:
        count = db.query(Opportunity).count()
        checks["opportunities_table"] = f"OK ({count} records)"
    except Exception as e:
        checks["opportunities_table"] = f"ERROR: {e}"

    try:
        opp = db.query(Opportunity).order_by(Opportunity.id.asc()).first()
        if opp:
            opp_id = int(opp.id)
            checks["sample_opportunity"] = f"OK (id={opp_id})"
        else:
            checks["sample_opportunity"] = "NO DATA"
    except Exception as e:
        checks["sample_opportunity"] = f"ERROR: {e}"

    checks["sam_api_key"] = "OK" if bool(get_effective_sam_api_key(db, user_id=getattr(current_user, "id", None)) or getattr(settings, "SAM_API_KEY", None)) else "MISSING"

    if opp_id:
        try:
            preds = find_predecessor_opportunities(db, opp_id)
            checks["predecessor_engine"] = f"OK ({len(preds)} matches)"
        except Exception as e:
            checks["predecessor_engine"] = f"ERROR: {e}"

        try:
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            research = search_usaspending_for_opportunity(opp, db=db)
            checks["usaspending"] = f"OK ({research.get('awards_found', 0)} awards)"
        except Exception as e:
            checks["usaspending"] = f"ERROR: {e}"
    else:
        checks["predecessor_engine"] = "SKIPPED"
        checks["usaspending"] = "SKIPPED"

    return {"status": "running", "checks": checks}
