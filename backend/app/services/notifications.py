from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.work_queue import HIGH, build_daily_work_queue


def build_notifications(db: Session, organization_id: int | None = None, limit: int = 20) -> dict:
    queue = build_daily_work_queue(db, organization_id=organization_id, limit=250)
    items = []
    for item in queue.get("items", []):
        if item.get("priority") != HIGH and item.get("type") not in {"QUOTE_FOLLOW_UP_DUE", "RFQ_CLOSING_SOON"}:
            continue
        items.append({
            "id": f"work-queue:{item.get('id')}",
            "kind": item.get("type"),
            "priority": item.get("priority"),
            "title": item.get("title"),
            "message": item.get("subtitle"),
            "action_url": item.get("action_url"),
            "action_label": item.get("action_label") or "Open Workspace",
            "opportunity": item.get("opportunity") or {},
            "created_from": "daily_work_queue",
        })
        if len(items) >= limit:
            break
    return {
        "items": items,
        "unread_count": len(items),
        "generated_at": queue.get("generated_at"),
    }
