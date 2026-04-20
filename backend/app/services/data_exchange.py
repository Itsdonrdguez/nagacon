from __future__ import annotations

import csv
import io
from typing import Iterable

from sqlalchemy.orm import Session

from app.repositories.providers import ProviderRepository
from app.services.vendor_service import list_quotes
from app.services.work_queue import build_daily_work_queue


def _csv_response(rows: Iterable[dict], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


def export_providers_csv(db: Session, organization_id: int | None = None, limit: int = 1000) -> str:
    rows, _ = ProviderRepository(db, organization_id=organization_id).list_rows(limit=limit, offset=0)
    fieldnames = [
        "provider_id",
        "company_name",
        "cage",
        "uei",
        "website",
        "email",
        "phone",
        "canonical_name",
        "identity_source",
        "identity_confidence",
        "nsn",
        "fsc",
        "nomenclature",
        "relationship_type",
        "source",
        "confidence",
    ]
    return _csv_response(rows, fieldnames)


def export_quotes_csv(db: Session, opportunity_id: int, organization_id: int | None = None) -> str:
    rows = []
    for quote in list_quotes(db, opportunity_id, organization_id=organization_id):
        rows.append({
            "quote_id": quote.id,
            "opportunity_id": quote.opportunity_id,
            "company_name": quote.company_name,
            "cage": quote.cage,
            "part_number": quote.part_number,
            "email": quote.email,
            "phone": quote.phone,
            "status": quote.status,
            "unit_price": quote.unit_price,
            "lead_time_days": quote.lead_time_days,
            "requested_at": quote.requested_at,
            "last_follow_up_at": quote.last_follow_up_at,
            "next_follow_up_at": quote.next_follow_up_at,
            "follow_up_count": quote.follow_up_count,
            "notes": quote.notes,
        })
    return _csv_response(rows, [
        "quote_id",
        "opportunity_id",
        "company_name",
        "cage",
        "part_number",
        "email",
        "phone",
        "status",
        "unit_price",
        "lead_time_days",
        "requested_at",
        "last_follow_up_at",
        "next_follow_up_at",
        "follow_up_count",
        "notes",
    ])


def export_work_queue_csv(db: Session, organization_id: int | None = None) -> str:
    queue = build_daily_work_queue(db, organization_id=organization_id)
    rows = []
    for item in queue.get("items", []):
        opp = item.get("opportunity") or {}
        rows.append({
            "item_id": item.get("id"),
            "type": item.get("type"),
            "priority": item.get("priority"),
            "title": item.get("title"),
            "subtitle": item.get("subtitle"),
            "solicitation_number": opp.get("solicitation_number"),
            "source": opp.get("source"),
            "agency": opp.get("agency"),
            "due_at": item.get("due_at"),
            "action_url": item.get("action_url"),
        })
    return _csv_response(rows, [
        "item_id",
        "type",
        "priority",
        "title",
        "subtitle",
        "solicitation_number",
        "source",
        "agency",
        "due_at",
        "action_url",
    ])
