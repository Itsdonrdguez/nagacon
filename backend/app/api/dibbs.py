from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.dibbs_adapter import pull_dibbs_by_fsc
from app.services.opportunity_store import upsert_opportunity

router = APIRouter(prefix="/api/dibbs", tags=["dibbs"])

@router.post("/preview")
def preview(payload: dict):
    """
    Preview results (no DB write).
    Body:
      {"fsc":"6515,6530", "limit": 25}
    """
    fsc = (payload.get("fsc") or "").strip()
    if not fsc:
        raise HTTPException(status_code=400, detail='payload must include: {"fsc":"6515"}')
    limit = int(payload.get("limit") or 25)
    items, diag = pull_dibbs_by_fsc(fsc=fsc, limit=limit, debug=False)
    return {"items": items, "diagnostic": diag}

@router.post("/pull")
def pull(payload: dict, db: Session = Depends(get_db)):
    """
    Pull results and upsert into DB.
    Body:
      {"fsc":"6515,6530", "limit": 25}
    """
    fsc = (payload.get("fsc") or "").strip()
    if not fsc:
        raise HTTPException(status_code=400, detail='payload must include: {"fsc":"6515"}')
    limit = int(payload.get("limit") or 25)

    items, diag = pull_dibbs_by_fsc(fsc=fsc, limit=limit, debug=False)

    n = 0
    for it in items:
        upsert_opportunity(db, it)
        n += 1
    db.commit()

    return {"inserted_or_updated": n, "diagnostic": diag}
