from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.services.workflow_audit import record_workflow_event
from app.utils.utc import utcnow


ALLOWED = {"DRAFT", "SUBMITTED", "AWARDED", "LOST", "NO_BID"}
TRANSITIONS = {
    "DRAFT": {"DRAFT", "SUBMITTED", "NO_BID"},
    "SUBMITTED": {"SUBMITTED", "AWARDED", "LOST"},
    "AWARDED": {"AWARDED"},
    "LOST": {"LOST"},
    "NO_BID": {"NO_BID"},
}


def get_submission(db: Session, opportunity_id: int) -> BidSubmission | None:
    return db.query(BidSubmission).filter(BidSubmission.opportunity_id == opportunity_id).first()


def upsert_submission(
    db: Session,
    opportunity_id: int,
    patch: dict,
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
    opportunity: Opportunity | None = None,
) -> BidSubmission:
    sub = get_submission(db, opportunity_id)
    if not sub:
        sub = BidSubmission(opportunity_id=opportunity_id, status="DRAFT")
        db.add(sub)
        db.flush()

    previous_status = str(getattr(sub, "status", "DRAFT") or "DRAFT").strip().upper()
    if "status" in patch and patch["status"]:
        st = str(patch["status"]).strip().upper()
        if st not in ALLOWED:
            st = "DRAFT"
        if st not in TRANSITIONS.get(previous_status, {previous_status}):
            raise ValueError(f"Submission status cannot move from {previous_status} to {st}")
        if st == "SUBMITTED":
            if not bool(patch.get("approved")):
                raise ValueError("explicit approval is required before marking a bid as submitted")
            submitted_price = patch.get("submitted_unit_price", getattr(sub, "submitted_unit_price", None))
            submitted_vendor_cage = patch.get("submitted_vendor_cage", getattr(sub, "submitted_vendor_cage", None))
            submitted_vendor_name = patch.get("submitted_vendor_name", getattr(sub, "submitted_vendor_name", None))
            planned_vendor_quote_id = patch.get("planned_vendor_quote_id", getattr(sub, "planned_vendor_quote_id", None))
            if submitted_price is None:
                raise ValueError("submitted_unit_price is required before marking a bid as submitted")
            if not submitted_vendor_cage and not submitted_vendor_name and not planned_vendor_quote_id:
                raise ValueError("vendor identity is required before marking a bid as submitted")
        if st in {"AWARDED", "LOST"} and not bool(patch.get("approved")):
            raise ValueError(f"explicit approval is required before marking a bid as {st}")
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

    sub.updated_at = utcnow()
    db.commit()
    db.refresh(sub)
    if sub.status != previous_status:
        record_workflow_event(
            db,
            opportunity_id=opportunity_id,
            organization_id=organization_id or getattr(opportunity, "organization_id", None),
            user_id=user_id,
            entity_type="bid_submission",
            entity_id=sub.id,
            action="status_transition",
            from_state=previous_status,
            to_state=sub.status,
            metadata={
                "submitted_unit_price": float(sub.submitted_unit_price) if sub.submitted_unit_price is not None else None,
                "submitted_vendor_cage": sub.submitted_vendor_cage,
                "planned_vendor_quote_id": sub.planned_vendor_quote_id,
                "approved": bool(patch.get("approved")),
                "approval_notes": patch.get("approval_notes"),
            },
        )
    return sub
