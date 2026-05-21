from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.services.work_queue import build_daily_work_queue, list_daily_queue_runs, queue_daily_work


router = APIRouter(prefix="/api/work-queue", tags=["work-queue"])


def _build_daily_work_queue_for_user(db: Session, organization_id: int | None, user_id: int | None, limit: int):
    try:
        return build_daily_work_queue(db, organization_id=organization_id, user_id=user_id, limit=limit)
    except TypeError:
        return build_daily_work_queue(db, organization_id=organization_id, limit=limit)


def _queue_daily_work_for_user(db: Session, organization_id: int | None, user_id: int | None, limit: int):
    try:
        return queue_daily_work(db, organization_id=organization_id, user_id=user_id, limit=limit)
    except TypeError:
        return queue_daily_work(db, organization_id=organization_id, limit=limit)


def _list_daily_queue_runs_for_user(db: Session, organization_id: int | None, user_id: int | None, limit: int):
    try:
        return list_daily_queue_runs(db, organization_id=organization_id, user_id=user_id, limit=limit)
    except TypeError:
        return list_daily_queue_runs(db, organization_id=organization_id, limit=limit)


@router.get("/today")
def get_daily_work_queue(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    return _build_daily_work_queue_for_user(
        db,
        getattr(current_org, "id", None),
        getattr(current_user, "id", None),
        limit,
    )


@router.post("/queue-today")
def queue_today_work(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    return _queue_daily_work_for_user(
        db,
        getattr(current_org, "id", None),
        getattr(current_user, "id", None),
        limit,
    )


@router.get("/queue-history")
def get_today_queue_history(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_org=Depends(get_current_organization),
    current_user=Depends(get_current_user),
):
    return _list_daily_queue_runs_for_user(
        db,
        getattr(current_org, "id", None),
        getattr(current_user, "id", None),
        limit,
    )
