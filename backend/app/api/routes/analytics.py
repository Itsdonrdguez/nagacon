from fastapi import APIRouter, Depends
from app.core.db import get_db
from app.services.analytics.metrics import get_analytics_summary

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("/summary")
def analytics_summary(db=Depends(get_db)):
    try:
        return get_analytics_summary(db)
    except Exception:
        return {"pipeline_count": 0, "status": "safe_fallback"}
