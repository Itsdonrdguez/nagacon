from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity, OpportunityAnalysis
from app.models.opportunity_file import OpportunityFile
from app.models.vendor import VendorLead, VendorQuote
from app.repositories.company import CompanyRepository
from app.services.workspace_service import build_research_profile, ensure_parsed, get_best_processed_document_data
from app.utils.solicitation_status import derive_solicitation_status


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clean_list(values: list[Any] | None) -> list[str]:
    return [str(value).strip() for value in list(values or []) if str(value or "").strip()]


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def _contains_any(text: str, candidates: list[str] | None) -> bool:
    haystack = text.lower()
    return any(candidate.lower() in haystack for candidate in _clean_list(candidates))


def _replace_underscores(value: str | None) -> str:
    return str(value or "").replace("_", " ").strip()


def _days_until_due(due_at: datetime | None) -> int | None:
    if due_at is None:
        return None
    return int((due_at - datetime.utcnow()).total_seconds() // 86400)


def _compute_strategic_fit(
    opp: Opportunity,
    profile,
    research_profile: dict[str, Any],
    document_data: dict[str, Any],
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    if not profile:
        return 55, reasons

    score = 35
    fsc = _clean_text(getattr(opp, "fsc", None) or research_profile.get("fsc_code"))
    naics = _clean_text(getattr(opp, "naics", None) or research_profile.get("naics_code"))
    agency = _clean_text(getattr(opp, "agency", None))
    place = _clean_text(getattr(opp, "place_of_performance", None))
    source = _clean_text(getattr(opp, "source", None)).upper()
    searchable_text = " ".join(
        [
            _clean_text(getattr(opp, "title", None)),
            _clean_text(getattr(opp, "raw_text", None)),
            _clean_text((document_data.get("summary") or {}).get("summary_text")),
        ]
    )

    preferred_dibbs_fsc = set(_clean_list(getattr(profile, "preferred_dibbs_fsc_codes", None)))
    preferred_sam_naics = set(_clean_list(getattr(profile, "preferred_sam_naics_codes", None)))
    preferred_agencies = _clean_list(getattr(profile, "preferred_sam_agencies", None))
    preferred_states = [item.upper() for item in _clean_list(getattr(profile, "preferred_sam_states", None))]
    preferred_keywords = _clean_list(getattr(profile, "preferred_sam_keywords", None))

    if source == "DIBBS" and fsc and fsc in preferred_dibbs_fsc:
        score += 30
        reasons.append(f"Matches preferred DIBBS FSC {fsc}.")
    elif source == "SAM" and naics and naics in preferred_sam_naics:
        score += 30
        reasons.append(f"Matches preferred SAM NAICS {naics}.")

    if agency and _contains_any(agency, preferred_agencies):
        score += 15
        reasons.append(f"Agency aligns with company targeting ({agency}).")

    place_upper = place.upper()
    if place_upper and any(state in place_upper for state in preferred_states):
        score += 10
        reasons.append("Place of performance aligns with preferred geography.")

    if searchable_text and _contains_any(searchable_text, preferred_keywords):
        score += 10
        reasons.append("Opportunity language aligns with targeted capability keywords.")

    if not reasons:
        score -= 10

    return _clamp(score), reasons


def _compute_capability_fit(
    research_profile: dict[str, Any],
    leads: list[VendorLead],
    quotes: list[VendorQuote],
    submission: BidSubmission | None,
    compliance_fields: dict[str, Any],
) -> tuple[int, list[str]]:
    score = 35
    reasons: list[str] = []
    approved_source_count = int(research_profile.get("approved_source_count") or 0)
    strong_leads = [lead for lead in leads if int(getattr(lead, "confidence", 0) or 0) >= 80]
    received_quotes = [quote for quote in quotes if _clean_text(getattr(quote, "status", None)).upper() == "RECEIVED"]
    priced_quotes = [quote for quote in received_quotes if getattr(quote, "unit_price", None) is not None]

    if approved_source_count > 0:
        score += 15
        reasons.append(f"{approved_source_count} approved source{'' if approved_source_count == 1 else 's'} identified.")
    if leads:
        score += 10
        reasons.append(f"{len(leads)} vendor lead{'' if len(leads) == 1 else 's'} available.")
    if strong_leads:
        score += 10
        reasons.append("High-confidence vendor leads are available.")
    if priced_quotes:
        score += 20
        reasons.append("At least one received vendor quote includes price.")
    elif received_quotes:
        score += 10
        reasons.append("At least one vendor has replied to the quote request.")
    if submission and (submission.planned_vendor_quote_id or submission.planned_vendor_cage or submission.planned_vendor_name):
        score += 10
        reasons.append("A planned submission vendor has already been selected.")
    if compliance_fields.get("nsn") and compliance_fields.get("quantity"):
        score += 5

    if not leads and not approved_source_count:
        score -= 15
    if not compliance_fields.get("quantity"):
        score -= 5

    return _clamp(score), reasons


def _compute_complexity(
    files: list[OpportunityFile],
    document_data: dict[str, Any],
    required_actions: list[str],
    review_flags: list[str],
) -> tuple[int, list[str]]:
    score = 35
    notes: list[str] = []
    doc_count = len(files)

    if doc_count >= 4:
        score += 15
        notes.append("Multiple solicitation documents increase review complexity.")
    elif doc_count <= 1 and document_data.get("filename"):
        score -= 10

    if len(required_actions) >= 5:
        score += 15
        notes.append("The solicitation has several required actions to track.")
    if len(review_flags) >= 3:
        score += 15
        notes.append("Several compliance items still need review.")
    if (document_data.get("pipeline") or {}).get("review_required"):
        score += 10
        notes.append("The primary solicitation document still has review-needed flags.")

    return _clamp(score), notes


def _compute_commercial_attractiveness(
    opp: Opportunity,
    research_profile: dict[str, Any],
    quotes: list[VendorQuote],
) -> tuple[int, list[str]]:
    score = 45
    reasons: list[str] = []
    due_status = derive_solicitation_status(getattr(opp, "due_at", None))
    nsn = _clean_text(research_profile.get("nsn"))
    approved_source_count = int(research_profile.get("approved_source_count") or 0)

    if _clean_text(getattr(opp, "source", None)).upper() == "DIBBS" and nsn:
        score += 15
        reasons.append("NSN-based DIBBS buy suggests repeat procurement behavior.")
    if approved_source_count > 0:
        score += 10
        reasons.append("Known approved sources improve sourcing confidence.")
    if quotes:
        score += 10
        reasons.append("Active quote activity suggests the opportunity is commercially actionable.")
    if due_status == "CLOSED":
        score -= 25

    return _clamp(score), reasons


def _compute_execution_feasibility(
    opp: Opportunity,
    files: list[OpportunityFile],
    leads: list[VendorLead],
    quotes: list[VendorQuote],
    submission: BidSubmission | None,
    review_flags: list[str],
) -> tuple[int, list[str]]:
    score = 45
    reasons: list[str] = []
    due_status = derive_solicitation_status(getattr(opp, "due_at", None))
    due_days = _days_until_due(getattr(opp, "due_at", None))
    received_priced_quotes = [
        quote for quote in quotes
        if _clean_text(getattr(quote, "status", None)).upper() == "RECEIVED" and getattr(quote, "unit_price", None) is not None
    ]

    if due_status == "CLOSED":
        score = 5
        reasons.append("The solicitation is already closed.")
        return _clamp(score), reasons

    if due_days is None:
        score -= 10
    elif due_days <= 1:
        score -= 25
        reasons.append("Very little time remains before the due date.")
    elif due_days <= 3:
        score -= 15
        reasons.append("Turnaround time is tight.")
    elif due_days <= 7:
        score += 5
    else:
        score += 15
        reasons.append("There is still enough runway to source and prepare the bid.")

    if files:
        score += 10
    else:
        score -= 20
    if leads:
        score += 10
    else:
        score -= 15
    if received_priced_quotes:
        score += 20
        reasons.append("A priced vendor response is already available.")
    if submission and (submission.planned_vendor_quote_id or submission.planned_vendor_cage or submission.planned_vendor_name):
        score += 10
        reasons.append("The workspace already has a planned submission vendor.")
    if review_flags:
        score -= min(20, len(review_flags) * 5)

    return _clamp(score), reasons


def _compute_risk(
    opp: Opportunity,
    files: list[OpportunityFile],
    leads: list[VendorLead],
    quotes: list[VendorQuote],
    missing_information: list[str],
    review_flags: list[str],
) -> tuple[int, list[str]]:
    score = 25
    reasons: list[str] = []
    due_status = derive_solicitation_status(getattr(opp, "due_at", None))
    due_days = _days_until_due(getattr(opp, "due_at", None))
    priced_quotes = [
        quote for quote in quotes
        if _clean_text(getattr(quote, "status", None)).upper() == "RECEIVED" and getattr(quote, "unit_price", None) is not None
    ]

    if due_status == "CLOSED":
        score = 95
        reasons.append("The solicitation is closed.")
        return _clamp(score), reasons

    if not files:
        score += 20
        reasons.append("No solicitation documents have been downloaded yet.")
    if not leads:
        score += 15
        reasons.append("No vendor leads or approved sources are ready yet.")
    if not priced_quotes:
        score += 10
        reasons.append("No priced vendor quote is available yet.")
    if due_days is not None and due_days <= 3 and not priced_quotes:
        score += 20
        reasons.append("The due date is close and sourcing is still incomplete.")
    if review_flags:
        score += min(25, len(review_flags) * 5)
        reasons.append("Compliance review items are still unresolved.")
    if missing_information:
        score += min(20, len(missing_information) * 4)
        reasons.append("Key solicitation facts are still missing or need confirmation.")

    return _clamp(score), reasons


def build_workspace_recommendation(
    db: Session,
    opp: Opportunity,
    *,
    parsed: dict[str, Any] | None = None,
    files: list[OpportunityFile] | None = None,
    leads: list[VendorLead] | None = None,
    quotes: list[VendorQuote] | None = None,
    submission: BidSubmission | None = None,
) -> dict[str, Any]:
    parsed = parsed or ensure_parsed(db, opp)
    files = files if files is not None else (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    leads = leads if leads is not None else (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opp.id)
        .order_by(VendorLead.updated_at.desc())
        .all()
    )
    quotes = quotes if quotes is not None else (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opp.id)
        .order_by(VendorQuote.updated_at.desc())
        .all()
    )
    if submission is None:
        submission = (
            db.query(BidSubmission)
            .filter(BidSubmission.opportunity_id == opp.id)
            .first()
        )

    profile = CompanyRepository(db).get_first_profile()
    research_profile = build_research_profile(opp, parsed)
    document_data = get_best_processed_document_data(opp, files=files)

    from app.services.document_pipeline import _build_compliance_artifact_content

    compliance = _build_compliance_artifact_content(db, opp)
    compliance_fields = dict(compliance.get("compliance_fields") or {})
    required_actions = _clean_list(compliance.get("required_actions") or compliance.get("submission_requirements"))
    missing_information = _clean_list(compliance.get("missing_information"))
    review_flags = _clean_list(compliance.get("review_flags"))

    strategic_fit, strategic_reasons = _compute_strategic_fit(opp, profile, research_profile, document_data)
    capability_fit, capability_reasons = _compute_capability_fit(research_profile, leads, quotes, submission, compliance_fields)
    complexity, complexity_notes = _compute_complexity(files, document_data, required_actions, review_flags)
    commercial_attractiveness, commercial_reasons = _compute_commercial_attractiveness(opp, research_profile, quotes)
    execution_feasibility, execution_reasons = _compute_execution_feasibility(opp, files, leads, quotes, submission, review_flags)
    risk, risk_reasons = _compute_risk(opp, files, leads, quotes, missing_information, review_flags)

    recommendation_score = _clamp(
        strategic_fit * 0.24
        + capability_fit * 0.20
        + commercial_attractiveness * 0.12
        + execution_feasibility * 0.24
        + (100 - complexity) * 0.10
        + (100 - risk) * 0.10
    )

    strengths = list(
        dict.fromkeys(
            [
                *strategic_reasons[:2],
                *capability_reasons[:2],
                *commercial_reasons[:1],
                *execution_reasons[:2],
                "Processed solicitation document is available." if document_data.get("filename") else None,
                "Compliance actions were extracted from the source document." if required_actions else None,
            ]
        )
    )
    strengths = [item for item in strengths if item]

    blockers = list(
        dict.fromkeys(
            [
                *risk_reasons[:3],
                *review_flags[:3],
                "No solicitation documents have been processed yet." if not document_data.get("filename") else None,
                "No vendor quote has been received yet." if not any(_clean_text(getattr(quote, "status", None)).upper() == "RECEIVED" for quote in quotes) else None,
                "No planned submission vendor has been selected yet." if not (submission and (submission.planned_vendor_quote_id or submission.planned_vendor_cage or submission.planned_vendor_name)) else None,
            ]
        )
    )
    blockers = [item for item in blockers if item]

    next_actions = list(
        dict.fromkeys(
            [
                "Download and process the solicitation documents." if not files else None,
                "Review the PDF-derived compliance flags and confirm any missing facts." if review_flags or missing_information else None,
                "Run vendor research and seed the quote tracker." if not leads else None,
                "Request pricing and lead time from targeted vendors." if not quotes else None,
                "Select the planned submission vendor and finalize submission pricing."
                if quotes and not (submission and (submission.planned_vendor_quote_id or submission.planned_vendor_cage or submission.planned_vendor_name))
                else None,
                "Prepare the final submission package and confirm submission status."
                if quotes and required_actions
                else None,
            ]
        )
    )
    next_actions = [item for item in next_actions if item]

    due_status = derive_solicitation_status(getattr(opp, "due_at", None))
    if due_status == "CLOSED":
        recommendation = "DO_NOT_BID"
    elif recommendation_score < 45 or (strategic_fit < 35 and capability_fit < 45):
        recommendation = "DO_NOT_BID"
    elif (
        recommendation_score >= 68
        and execution_feasibility >= 55
        and risk <= 55
        and (bool(leads) or int(research_profile.get("approved_source_count") or 0) > 0)
    ):
        recommendation = "BID"
    else:
        recommendation = "NEEDS_REVIEW"

    confidence = _clamp(
        45
        + (10 if document_data.get("filename") else 0)
        + (10 if required_actions else 0)
        + min(15, len(files) * 3)
        + min(10, len(leads) * 2)
        + (10 if any(getattr(quote, "unit_price", None) is not None for quote in quotes) else 0)
        - (10 if review_flags else 0)
    )

    bid_posture = {
        "BID": "bid",
        "NEEDS_REVIEW": "needs_review",
        "DO_NOT_BID": "research_only" if due_status == "CLOSED" else "do_not_bid",
    }[recommendation]

    reason_pool = []
    if strengths:
        reason_pool.extend(strengths[:2])
    if blockers:
        reason_pool.extend(blockers[:2])
    reasons = list(dict.fromkeys([item for item in reason_pool if item]))[:4]

    recommendation_label = _replace_underscores(recommendation).title()
    summary_parts = [recommendation_label]
    if reasons:
        summary_parts.append(": ")
        summary_parts.append(" ".join(reasons[:2]))
    summary = "".join(summary_parts).strip()

    risk_flags = [
        {"severity": "high" if recommendation == "DO_NOT_BID" else "medium", "detail": item}
        for item in blockers[:6]
    ]

    return {
        "recommendation": recommendation,
        "recommendation_score": recommendation_score,
        "confidence": confidence,
        "bid_posture": bid_posture,
        "summary": summary,
        "score_breakdown": {
            "strategic_fit": strategic_fit,
            "capability_fit": capability_fit,
            "complexity": complexity,
            "commercial_attractiveness": commercial_attractiveness,
            "execution_feasibility": execution_feasibility,
            "risk": risk,
        },
        "strengths": strengths,
        "blockers": blockers,
        "reasons": reasons,
        "next_actions": next_actions,
        "risk_flags": risk_flags,
        "workspace_signals": {
            "document_count": len(files),
            "processed_document": document_data.get("filename"),
            "required_action_count": len(required_actions),
            "review_flag_count": len(review_flags),
            "vendor_lead_count": len(leads),
            "quote_count": len(quotes),
            "received_quote_count": sum(
                1 for quote in quotes if _clean_text(getattr(quote, "status", None)).upper() == "RECEIVED"
            ),
            "approved_source_count": int(research_profile.get("approved_source_count") or 0),
        },
    }


def upsert_recommendation_analysis(
    db: Session,
    opp_id: int,
    recommendation: dict[str, Any],
    *,
    ai_summary: str | None = None,
) -> OpportunityAnalysis:
    existing = (
        db.query(OpportunityAnalysis)
        .filter(OpportunityAnalysis.opportunity_id == opp_id)
        .first()
    )
    if existing:
        existing.priority_score = int(recommendation.get("recommendation_score") or 0)
        existing.fit_score = int((recommendation.get("score_breakdown") or {}).get("strategic_fit") or 0)
        existing.risk_flags = list(recommendation.get("risk_flags") or [])
        existing.ai_summary = ai_summary or recommendation.get("summary")
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    rec = OpportunityAnalysis(
        opportunity_id=opp_id,
        priority_score=int(recommendation.get("recommendation_score") or 0),
        fit_score=int((recommendation.get("score_breakdown") or {}).get("strategic_fit") or 0),
        risk_flags=list(recommendation.get("risk_flags") or []),
        ai_summary=ai_summary or recommendation.get("summary"),
        updated_at=datetime.utcnow(),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec
