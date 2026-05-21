from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_organization, get_current_user
from app.services.dibbs.detail_enrichment_playwright import enrich_dibbs_batch
from app.services.import_run_service import complete_import_run, start_import_run

router = APIRouter(
    prefix="/api/dibbs",
    tags=["dibbs"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


@router.post("/enrich-playwright")
def enrich(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    limit = int(payload.get("limit") or 10)
    source = str(payload.get("source") or "DIBBS")
    debug = bool(payload.get("debug") or False)
    run = start_import_run(
        db,
        source="DIBBS_ENRICHMENT_PLAYWRIGHT",
        run_kind="dibbs_enrichment",
        request_payload=payload,
        organization_id=getattr(current_org, "id", None),
        user_id=getattr(current_user, "id", None),
    )
    try:
        result = enrich_dibbs_batch(db=db, limit=limit, source=source, debug=debug)
        complete_import_run(
            db,
            run,
            status="completed" if not int(result.get("failed") or 0) else "partial_success",
            result_payload=result,
            row_count=int(result.get("requested_limit") or 0),
            updated_count=int(result.get("enriched") or 0),
            skipped_count=int(result.get("failed") or 0),
        )
        return result
    except Exception as exc:
        complete_import_run(db, run, status="failed", error_message=str(exc))
        raise
