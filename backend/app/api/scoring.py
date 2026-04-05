from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.services.scoring_engine import run_scoring

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


@router.post("/run")
def run(payload: dict, db: Session = Depends(get_db)):
    source = payload.get("source")
    limit = int(payload.get("limit") or 200)
    only_status = payload.get("only_status", "new")
    return run_scoring(db=db, source=source, limit=limit, only_status=only_status)


@router.post("/run_all")
def run_all(payload: dict, db: Session = Depends(get_db)):
    source = payload.get("source")
    limit = int(payload.get("limit") or 1000000)
    only_status = payload.get("only_status", None)  # score all statuses unless specified
    return run_scoring(db=db, source=source, limit=limit, only_status=only_status)
