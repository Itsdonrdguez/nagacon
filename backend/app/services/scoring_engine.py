from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity, OpportunityAnalysis


def _clamp(n: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, n))


def _risk(code: str, severity: str, detail: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail}


def score_opportunity(db: Session, opp: Opportunity) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    """
    Deterministic v1 scoring.

    IMPORTANT (Step 5.1):
    - NSN duplicates are NOT treated as a risk (no DUPLICATE_NSN flags).
      NSNs represent product codes; multiple RFQs for same NSN are normal and expected.

    - NO fit score (fit_score remains 0 and is ignored).
    - Priority is actionability + urgency - missing data.

    Returns: (priority_score, risk_flags, breakdown)
    """
    score = 50
    flags: list[dict[str, Any]] = []
    breakdown = {"base": 50, "urgency": 0, "completeness": 0, "noise": 0}

    # --- Urgency ---
    if opp.due_at is None:
        score -= 10
        breakdown["urgency"] -= 10
        flags.append(_risk("NO_DUE_DATE", "med", "No due date found."))
    else:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        due = opp.due_at.replace(tzinfo=None)
        delta_days = (due - now).days

        if delta_days < 0:
            score -= 15
            breakdown["urgency"] -= 15
            flags.append(_risk("OVERDUE", "high", "Due date is in the past."))
        elif delta_days <= 7:
            score += 20
            breakdown["urgency"] += 20
            flags.append(_risk("DUE_SOON", "med", "Due within 7 days."))
        elif delta_days <= 14:
            score += 10
            breakdown["urgency"] += 10
            flags.append(_risk("DUE_IN_14_DAYS", "low", "Due within 14 days."))

    # --- Completeness ---
    title = (opp.title or "").strip()
    if not title or title.lower() in {"request rejected", "access denied"}:
        score -= 10
        breakdown["completeness"] -= 10
        flags.append(_risk("BAD_TITLE", "high", "Title looks missing or blocked."))
    else:
        score += 5
        breakdown["completeness"] += 5

    if not (opp.raw_text or "").strip():
        score -= 10
        breakdown["completeness"] -= 10
        flags.append(_risk("MISSING_RAW_TEXT", "low", "Package details (raw_text) not captured yet."))

    # --- Minor noise ---
    sol = (opp.solicitation_number or "")
    if "package view" in sol.lower() or "»" in sol:
        score -= 5
        breakdown["noise"] -= 5
        flags.append(_risk("BAD_SOLICITATION_FORMAT", "low", "Solicitation number contains extra suffix text."))

    return _clamp(int(score)), flags, breakdown


def upsert_analysis(
    db: Session,
    opp_id: int,
    priority_score: int,
    risk_flags: list[dict[str, Any]],
) -> OpportunityAnalysis:
    existing = (
        db.query(OpportunityAnalysis)
        .filter(OpportunityAnalysis.opportunity_id == opp_id)
        .first()
    )
    if existing:
        existing.priority_score = priority_score
        existing.risk_flags = risk_flags
        existing.updated_at = datetime.utcnow()
        return existing

    rec = OpportunityAnalysis(
        opportunity_id=opp_id,
        fit_score=0,  # ignored
        priority_score=priority_score,
        risk_flags=risk_flags,
        ai_summary=None,
        updated_at=datetime.utcnow(),
    )
    db.add(rec)
    return rec


def run_scoring(
    db: Session,
    source: str | None = None,
    limit: int = 200,
    only_status: str | None = "new",
) -> dict[str, int]:
    q = db.query(Opportunity)
    if source:
        q = q.filter(Opportunity.source == source)
    if only_status:
        q = q.filter(Opportunity.status == only_status)

    opps = q.order_by(Opportunity.id.desc()).limit(limit).all()

    scored = 0
    updated = 0

    for opp in opps:
        priority, flags, _breakdown = score_opportunity(db, opp)
        upsert_analysis(db, opp.id, priority, flags)
        scored += 1
        updated += 1

    db.commit()
    return {"scored": scored, "updated": updated, "skipped": 0}
