from __future__ import annotations

from datetime import datetime
from typing import Any

from api_client import get_json, post, patch_json


def get_pipeline_by_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    return get_json(f"/api/pipeline/by-opportunity/{opportunity_id}")


def create_or_get_pipeline(opportunity_id: int) -> dict[str, Any]:
    return post(f"/api/pipeline/by-opportunity/{opportunity_id}", {})


def update_pipeline(
    pipeline_id: int,
    *,
    decision_status: str | None = None,
    owner: str | None = None,
    priority: str | None = None,
    probability_of_win: float | None = None,
    notes: str | None = None,
    target_submit_date: datetime | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if decision_status is not None:
        payload["decision_status"] = decision_status
    if owner is not None:
        payload["owner"] = owner
    if priority is not None:
        payload["priority"] = priority
    if probability_of_win is not None:
        payload["probability_of_win"] = probability_of_win
    if notes is not None:
        payload["notes"] = notes
    if target_submit_date is not None:
        payload["target_submit_date"] = target_submit_date.isoformat()

    return patch_json(f"/api/pipeline/{pipeline_id}", payload)
