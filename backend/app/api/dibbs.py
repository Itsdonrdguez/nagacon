from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.dibbs_adapter import pull_dibbs_by_fsc
from app.services.ingest_enrichment import enrich_dibbs_opportunities_after_ingest
from app.services.opportunity_store import upsert_opportunity

router = APIRouter(prefix="/api/dibbs", tags=["dibbs"])


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

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
    opportunity_ids: list[int] = []
    for it in items:
        opp = upsert_opportunity(db, it)
        if getattr(opp, "id", None):
            opportunity_ids.append(opp.id)
        n += 1
    db.commit()
    opportunity_ids = [opp_id for opp_id in opportunity_ids if opp_id]

    enrichment = None
    if _as_bool(payload.get("auto_enrich_parts"), True) and opportunity_ids:
        enrichment = enrich_dibbs_opportunities_after_ingest(
            db,
            opportunity_ids,
            queue_nsn_build=_as_bool(payload.get("queue_nsn_build"), False),
            max_items=len(opportunity_ids),
        )

    return {"inserted_or_updated": n, "diagnostic": diag, "part_finder_enrichment": enrichment}
