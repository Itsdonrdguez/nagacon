from __future__ import annotations

from datetime import datetime
from typing import Any

from api_client import get_bytes, get_json, post


def workspace_summary(opportunity_id: int) -> dict[str, Any]:
    return get_json("/api/workspace/summary", {"opp_id": opportunity_id})


def workspace_parse(opportunity_id: int) -> dict[str, Any]:
    return post("/api/workspace/parse", {"opportunity_id": opportunity_id})


def workspace_generate_checklist(opportunity_id: int) -> dict[str, Any]:
    return post("/api/workspace/generate/checklist", {"opportunity_id": opportunity_id})


def workspace_generate_vendors(opportunity_id: int) -> dict[str, Any]:
    return post("/api/workspace/generate/vendors", {"opportunity_id": opportunity_id})


def workspace_generate_email(opportunity_id: int) -> dict[str, Any]:
    return post("/api/workspace/generate/email", {"opportunity_id": opportunity_id})


def workspace_save_decision(opportunity_id: int, decision_status: str, decision_note: str | None) -> dict[str, Any]:
    return post(
        "/api/workspace/decision",
        {
            "opportunity_id": opportunity_id,
            "decision_status": decision_status,
            "decision_note": decision_note,
        },
    )


def workspace_create_task(opportunity_id: int, task_type: str, due_at: datetime | None = None, notes: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_type": task_type,
        "due_at": due_at.isoformat() if due_at else None,
        "notes": notes,
    }
    return post(f"/api/workspace/tasks?opp_id={opportunity_id}", payload)


def workspace_export_zip(opportunity_id: int) -> bytes:
    return get_bytes("/api/workspace/export.zip", {"opp_id": opportunity_id})
