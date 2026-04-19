from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission


ALLOWED = {"DRAFT", "SUBMITTED", "AWARDED", "LOST", "NO_BID"}


def get_submission(db: Session, opportunity_id: int) -> BidSubmission | None:
    return db.query(BidSubmission).filter(BidSubmission.opportunity_id == opportunity_id).first()


def upsert_submission(db: Session, opportunity_id: int, patch: dict) -> BidSubmission:
    sub = get_submission(db, opportunity_id)
    if not sub:
        sub = BidSubmission(opportunity_id=opportunity_id, status="DRAFT")
        db.add(sub)
        db.flush()

    if "status" in patch and patch["status"]:
        st = str(patch["status"]).strip().upper()
        if st not in ALLOWED:
            st = "DRAFT"
        sub.status = st

    for k in [
        "submitted_at",
        "submitted_unit_price",
        "submitted_vendor_cage",
        "submitted_vendor_name",
        "planned_vendor_quote_id",
        "planned_vendor_cage",
        "planned_vendor_name",
        "awarded_at",
        "award_amount",
        "winning_vendor_cage",
        "winning_vendor_name",
        "outcome_summary",
        "notes",
    ]:
        if k in patch:
            setattr(sub, k, patch[k])

    sub.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sub)
    return sub
