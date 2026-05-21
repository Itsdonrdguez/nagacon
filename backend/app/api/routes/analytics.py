from fastapi import APIRouter, Depends
from app.core.db import get_db
from app.core.deps import get_current_organization, get_current_user
from app.services.analytics.metrics import get_analytics_summary

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)

@router.get("/summary")
def analytics_summary(db=Depends(get_db)):
    try:
        return get_analytics_summary(db)
    except Exception:
        return {"pipeline_count": 0, "status": "safe_fallback"}
