from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.pipeline_item import PipelineItem
from app.models.vendor import VendorQuote


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _clean_text(value).upper()


def _matches(current: Opportunity, candidate: Opportunity) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if _norm(current.source) and _norm(current.source) == _norm(candidate.source):
        score += 2
        reasons.append(f"Same source: {_clean_text(current.source)}")
    if _norm(current.naics) and _norm(current.naics) == _norm(candidate.naics):
        score += 4
        reasons.append(f"Same NAICS: {_clean_text(current.naics)}")
    if _norm(current.fsc) and _norm(current.fsc) == _norm(candidate.fsc):
        score += 3
        reasons.append(f"Same FSC/PSC: {_clean_text(current.fsc)}")
    if _norm(current.set_aside) and _norm(current.set_aside) == _norm(candidate.set_aside):
        score += 2
        reasons.append(f"Same set-aside: {_clean_text(current.set_aside)}")
    if _norm(current.agency) and _norm(current.agency) == _norm(candidate.agency):
        score += 3
        reasons.append("Same agency")
    elif _norm(current.agency) and _norm(candidate.agency) and _norm(current.agency).split(".")[0] == _norm(candidate.agency).split(".")[0]:
        score += 1
        reasons.append("Same department family")

    return score, reasons


def _normalize_outcome(submission: BidSubmission | None, pipeline: PipelineItem | None) -> str:
    submission_status = _norm(getattr(submission, "status", None))
    if submission_status in {"AWARDED", "LOST", "NO_BID", "SUBMITTED"}:
        return submission_status

    decision_status = _norm(getattr(getattr(pipeline, "decision_status", None), "value", getattr(pipeline, "decision_status", None)))
    if decision_status in {"NO_BID", "SUBMITTED", "BID", "IN_PROGRESS", "REVIEW", "NEW"}:
        return decision_status

    return "UNKNOWN"


def _extract_reason_snippets(*values: Any, limit: int = 4) -> list[str]:
    snippets: list[str] = []
    seen: set[str] = set()
    generic = {
        "no notes",
        "n/a",
        "na",
        "none",
        "unknown",
    }
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        for chunk in re.split(r"[\r\n]+|[;]+|(?<=[.!?])\s+", text):
            cleaned = re.sub(r"\s+", " ", chunk).strip(" -\t\r\n")
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in generic or len(cleaned) < 12:
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            snippets.append(cleaned)
            if len(snippets) >= limit:
                return snippets
    return snippets


def _summarize_vendor_responses(quotes: list[VendorQuote]) -> dict[str, Any]:
    statuses = Counter(_norm(getattr(quote, "status", None)) or "UNKNOWN" for quote in quotes)
    priced_count = sum(1 for quote in quotes if getattr(quote, "unit_price", None) is not None)
    received_count = statuses.get("RECEIVED", 0)
    requested_count = statuses.get("REQUESTED", 0)
    no_bid_count = statuses.get("NO_BID", 0)
    invalid_count = statuses.get("INVALID", 0)
    follow_up_total = sum(int(getattr(quote, "follow_up_count", 0) or 0) for quote in quotes)

    if priced_count > 0 or received_count >= 2:
        quality = "strong"
    elif received_count > 0:
        quality = "usable"
    elif requested_count > 0:
        quality = "pending"
    elif no_bid_count > 0 or invalid_count > 0:
        quality = "thin"
    else:
        quality = "none"

    summary_bits: list[str] = []
    if priced_count:
        summary_bits.append(f"{priced_count} priced repl{'y' if priced_count == 1 else 'ies'}")
    if received_count and received_count != priced_count:
        summary_bits.append(f"{received_count} vendor repl{'y' if received_count == 1 else 'ies'}")
    if requested_count:
        summary_bits.append(f"{requested_count} request{'s' if requested_count != 1 else ''} out")
    if no_bid_count:
        summary_bits.append(f"{no_bid_count} no-bid response{'s' if no_bid_count != 1 else ''}")
    if follow_up_total:
        summary_bits.append(f"{follow_up_total} follow-up{'s' if follow_up_total != 1 else ''}")
    summary = ", ".join(summary_bits) if summary_bits else "No quote-response history recorded."

    return {
        "quality": quality,
        "summary": summary,
        "counts": dict(statuses),
        "priced_count": priced_count,
        "received_count": received_count,
        "requested_count": requested_count,
        "no_bid_count": no_bid_count,
        "follow_up_total": follow_up_total,
    }


def build_solicitation_memory(db: Session, opp: Opportunity, *, limit: int = 6) -> dict[str, Any]:
    opportunities = (
        db.query(Opportunity)
        .filter(Opportunity.id != opp.id)
        .order_by(Opportunity.posted_at.desc().nullslast(), Opportunity.id.desc())
        .limit(250)
        .all()
    )

    candidate_ids = [candidate.id for candidate in opportunities]
    submissions_by_opp = {
        row.opportunity_id: row
        for row in db.query(BidSubmission).filter(BidSubmission.opportunity_id.in_(candidate_ids)).all()
    } if candidate_ids else {}
    pipelines_by_opp = {
        row.opportunity_id: row
        for row in db.query(PipelineItem).filter(PipelineItem.opportunity_id.in_(candidate_ids)).all()
    } if candidate_ids else {}
    quotes_by_opp: dict[int, list[VendorQuote]] = defaultdict(list)
    if candidate_ids:
        for row in db.query(VendorQuote).filter(VendorQuote.opportunity_id.in_(candidate_ids)).all():
            quotes_by_opp[row.opportunity_id].append(row)

    rows: list[dict[str, Any]] = []
    for candidate in opportunities:
        score, reasons = _matches(opp, candidate)
        if score <= 0:
            continue
        submission = submissions_by_opp.get(candidate.id)
        pipeline = pipelines_by_opp.get(candidate.id)
        quotes = quotes_by_opp.get(candidate.id, [])
        outcome = _normalize_outcome(submission, pipeline)
        rationale = _extract_reason_snippets(
            getattr(pipeline, "notes", None),
            getattr(submission, "outcome_summary", None),
            getattr(submission, "notes", None),
            *[getattr(quote, "notes", None) for quote in quotes],
        )
        vendor_response = _summarize_vendor_responses(quotes)
        rows.append(
            {
                "opportunity_id": candidate.id,
                "title": getattr(candidate, "display_title", None) or candidate.title,
                "source": candidate.source,
                "agency": candidate.agency,
                "naics_code": candidate.naics,
                "fsc_code": candidate.fsc,
                "set_aside_type": candidate.set_aside,
                "due_at": candidate.due_at.isoformat() if candidate.due_at else None,
                "outcome": outcome,
                "similarity_score": score,
                "match_reasons": reasons[:4],
                "decision_rationale": rationale,
                "outcome_summary": _clean_text(getattr(submission, "outcome_summary", None)) or None,
                "vendor_response_quality": vendor_response["quality"],
                "vendor_response_summary": vendor_response["summary"],
                "vendor_response_counts": vendor_response["counts"],
                "received_quote_count": vendor_response["received_count"],
                "priced_quote_count": vendor_response["priced_count"],
                "workspace_url": f"/workspace/{candidate.id}",
            }
        )

    rows.sort(key=lambda item: (-int(item.get("similarity_score") or 0), item.get("due_at") or "", str(item.get("title") or "")))
    top_rows = rows[:limit]

    outcome_counts = Counter(row["outcome"] for row in rows)
    response_quality_counts = Counter(row.get("vendor_response_quality") or "none" for row in rows)
    agency_counts = Counter(_clean_text(row.get("agency")) for row in rows if _clean_text(row.get("agency")))
    rationale_counts = Counter()
    for row in rows:
        for snippet in row.get("decision_rationale") or []:
            rationale_counts[snippet] += 1

    pattern_notes: list[str] = []
    if _clean_text(opp.naics):
        matching_naics = [row for row in rows if _norm(row.get("naics_code")) == _norm(opp.naics)]
        if matching_naics:
            pattern_notes.append(f"{len(matching_naics)} prior opportunity record(s) share NAICS {_clean_text(opp.naics)}.")
    if _clean_text(opp.fsc):
        matching_fsc = [row for row in rows if _norm(row.get("fsc_code")) == _norm(opp.fsc)]
        if matching_fsc:
            pattern_notes.append(f"{len(matching_fsc)} prior opportunity record(s) share FSC/PSC {_clean_text(opp.fsc)}.")
    if outcome_counts.get("NO_BID"):
        pattern_notes.append(f"No-bid outcomes appear in {outcome_counts.get('NO_BID')} similar record(s).")
    if outcome_counts.get("AWARDED"):
        pattern_notes.append(f"Awarded outcomes appear in {outcome_counts.get('AWARDED')} similar record(s).")
    if response_quality_counts.get("strong"):
        pattern_notes.append(f"Strong vendor response showed up in {response_quality_counts.get('strong')} similar record(s).")
    if response_quality_counts.get("pending"):
        pattern_notes.append(f"Pending vendor outreach shows up in {response_quality_counts.get('pending')} similar record(s).")
    common_rationale = [snippet for snippet, count in rationale_counts.most_common(3) if count > 1]
    for snippet in common_rationale[:2]:
        pattern_notes.append(f"Repeated note in local history: {snippet}")
    if not pattern_notes and rows:
        pattern_notes.append("Similar opportunities exist, but no single dominant pattern stands out yet.")
    if not rows:
        pattern_notes.append("No similar opportunity history is available yet in this workspace database.")

    outcome_patterns = [
        {
            "outcome": outcome,
            "count": count,
            "label": outcome.replace("_", " ").title(),
        }
        for outcome, count in outcome_counts.most_common()
    ]
    response_patterns = [
        {
            "quality": quality,
            "count": count,
            "label": quality.replace("_", " ").title(),
        }
        for quality, count in response_quality_counts.most_common()
    ]
    agency_patterns = [
        {
            "agency": agency,
            "count": count,
        }
        for agency, count in agency_counts.most_common(5)
    ]
    repeat_rationale_patterns = [
        {
            "text": snippet,
            "count": count,
        }
        for snippet, count in rationale_counts.most_common(6)
        if count > 1
    ]
    history_signals: list[str] = []
    if outcome_patterns:
        top = outcome_patterns[0]
        history_signals.append(f"Most common local outcome: {top['label']} ({top['count']}).")
    if response_patterns:
        top = response_patterns[0]
        history_signals.append(f"Typical vendor response pattern: {top['label']} ({top['count']}).")
    if agency_patterns:
        top = agency_patterns[0]
        history_signals.append(f"Most common related buyer: {top['agency']} ({top['count']}).")
    if repeat_rationale_patterns:
        top = repeat_rationale_patterns[0]
        history_signals.append(f"Repeated local note: {top['text']}")

    top_pattern = outcome_counts.most_common(1)[0][0] if outcome_counts else None
    strongest_response = response_quality_counts.most_common(1)[0][0] if response_quality_counts else None

    summary = (
        f"Found {len(rows)} similar opportunity record(s) in local history."
        if rows
        else "No similar local opportunity history is available yet."
    )
    if top_pattern:
        summary += f" Most common prior outcome: {top_pattern.replace('_', ' ').title()}."
    if strongest_response and strongest_response != "none":
        summary += f" Typical vendor response quality: {strongest_response.title()}."

    return {
        "summary": summary,
        "match_count": len(rows),
        "top_outcome_pattern": top_pattern,
        "outcome_counts": dict(outcome_counts),
        "response_quality_counts": dict(response_quality_counts),
        "strongest_response_pattern": strongest_response,
        "common_rationale": common_rationale,
        "outcome_patterns": outcome_patterns,
        "response_patterns": response_patterns,
        "agency_patterns": agency_patterns,
        "repeat_rationale_patterns": repeat_rationale_patterns,
        "history_signals": history_signals,
        "pattern_notes": pattern_notes[:8],
        "examples": top_rows,
    }
