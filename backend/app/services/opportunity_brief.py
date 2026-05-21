from __future__ import annotations

from datetime import datetime
from typing import Any

from app.utils.utc import utcnow


def _clean(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("value", "label", "text", "name"):
            if key in value:
                return _clean(value.get(key))
    text = str(value or "").strip()
    return text or None


def _days_until(value: datetime | None, now: datetime | None = None) -> int | None:
    if not value:
        return None
    current = now or utcnow()
    return (value.date() - current.date()).days


def _first_text(*values: Any) -> str | None:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return None


def _presence_value(facts: dict[str, Any] | None, key: str, fallback: Any = None) -> Any:
    if isinstance((facts or {}).get(key), dict):
        value = (facts or {}).get(key, {}).get("value")
        return fallback if value in (None, "") else value
    return fallback


def _clean_list(values: list[Any] | None) -> list[str]:
    return [str(value).strip() for value in list(values or []) if str(value or "").strip()]


def _label_from_count(count: int, low_cutoff: int = 2, high_cutoff: int = 6) -> str:
    if count >= high_cutoff:
        return "high"
    if count > low_cutoff:
        return "medium"
    return "low"


def _infer_response_type(source: str | None, submission_method: str | None, attachments: list[str], evaluation_factors: list[str]) -> str:
    text = " ".join([str(source or ""), str(submission_method or ""), " ".join(attachments), " ".join(evaluation_factors)]).lower()
    if "quote" in text and "proposal" not in text:
        return "quote"
    if "capability statement" in text:
        return "capability_statement"
    if "technical" in text or "past performance" in text or attachments:
        return "proposal"
    return "proposal" if str(source or "").upper() == "SAM" else "quote"


def _infer_evaluation_basis(evaluation_factors: list[str], summary_text: str | None) -> str | None:
    factors_text = " ".join(evaluation_factors).upper()
    summary = str(summary_text or "").upper()
    if "LOWEST PRICE" in factors_text or "LPTA" in factors_text or "LPTA" in summary:
        return "lpta"
    if any(token in factors_text for token in ["TECHNICAL APPROACH", "PAST PERFORMANCE", "MANAGEMENT APPROACH", "KEY PERSONNEL"]):
        return "best_value"
    if "PRICE" in factors_text:
        return "price_driven"
    return None


def build_contract_brief(
    opp: Any,
    normalized_facts: dict[str, Any] | None = None,
    *,
    parsed_summary: dict[str, Any] | None = None,
    document_count: int = 0,
    vendor_count: int = 0,
    quote_count: int = 0,
) -> dict[str, Any]:
    facts = normalized_facts or {}
    parsed = parsed_summary or {}
    due_at = getattr(opp, "due_at", None)
    nsn = _clean(facts.get("nsn")) or _clean(parsed.get("nsn"))
    nomenclature = (
        _clean(facts.get("nomenclature"))
        or _clean(parsed.get("nomenclature"))
        or _clean(getattr(opp, "title", None))
    )
    set_aside = (
        _clean(getattr(opp, "set_aside", None))
        or _clean(facts.get("set_aside"))
        or _clean(facts.get("set_aside_type"))
    )
    return {
        "source": _clean(getattr(opp, "source", None)),
        "solicitation_number": _clean(getattr(opp, "solicitation_number", None)),
        "title": _clean(getattr(opp, "display_title", None)) or _clean(getattr(opp, "title", None)),
        "agency": _clean(getattr(opp, "agency", None)),
        "due_at": due_at.isoformat() if due_at else None,
        "days_until_due": _days_until(due_at),
        "set_aside_type": set_aside,
        "fsc": _clean(getattr(opp, "fsc", None)) or _clean(facts.get("fsc")),
        "naics": _clean(getattr(opp, "naics", None)) or _clean(facts.get("naics")),
        "nsn": nsn,
        "nomenclature": nomenclature,
        "has_documents": document_count > 0,
        "has_vendor_candidates": vendor_count > 0,
        "has_quotes": quote_count > 0,
    }


def build_procurement_profile(
    opp: Any,
    normalized_facts: dict[str, Any] | None = None,
    parsed_summary: dict[str, Any] | None = None,
    document_data: dict[str, Any] | None = None,
    compliance_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts = normalized_facts or {}
    parsed = parsed_summary or {}
    document_data = document_data or {}
    compliance_json = compliance_json or {}
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    source = _first_text(getattr(opp, "source", None))
    agency = _first_text(getattr(opp, "agency", None))
    sub_agency = _first_text(getattr(opp, "sub_agency", None))
    office = _first_text(getattr(opp, "office", None))
    nsn = _first_text(_presence_value(facts, "nsn"), parsed.get("nsn"))
    fsc = _first_text(_presence_value(facts, "fsc"), getattr(opp, "fsc", None))
    naics = _first_text(_presence_value(facts, "naics"), getattr(opp, "naics", None))
    set_aside = _first_text(_presence_value(facts, "set_aside"), getattr(opp, "set_aside", None))
    submission_method = _first_text(_presence_value(facts, "submission_method"))
    submission_office = _first_text(((facts.get("poc") or {}).get("submission_office") or {}).get("value"))
    contact_name = _first_text(((facts.get("poc") or {}).get("name") or {}).get("value"))
    contact_email = _first_text(((facts.get("poc") or {}).get("email") or {}).get("value"))
    document_set = dict(compliance_json.get("document_set") or {})
    merged_fields = dict(document_set.get("merged_fields") or {})
    service_signals = dict(document_set.get("service_signals") or {})
    evaluation_factors = _clean_list(compliance_json.get("evaluation_factors") or document_set.get("evaluation_factors"))
    required_attachments = _clean_list(compliance_json.get("required_attachments") or document_set.get("required_attachments"))
    amendments = list(document_set.get("amendment_tracker") or [])
    review_flags = _clean_list(compliance_json.get("review_flags"))
    missing_information = _clean_list(compliance_json.get("missing_information"))
    point_of_contact = list(raw_payload.get("pointOfContact") or [])
    primary_contact = point_of_contact[0] if point_of_contact else {}
    place_payload = dict(raw_payload.get("placeOfPerformance") or {})
    place_city = ((place_payload.get("city") or {}) if isinstance(place_payload.get("city"), dict) else {}) or {}
    place_state = ((place_payload.get("state") or {}) if isinstance(place_payload.get("state"), dict) else {}) or {}
    place_country = ((place_payload.get("country") or {}) if isinstance(place_payload.get("country"), dict) else {}) or {}
    place_of_performance_hint = ", ".join(
        part
        for part in [
            _first_text(place_city.get("name"), place_payload.get("city")),
            _first_text(place_state.get("name"), place_payload.get("state")),
            _first_text(place_payload.get("zip")),
            _first_text(place_country.get("name"), place_payload.get("country")),
        ]
        if part
    ) or None
    due_at = getattr(opp, "due_at", None)
    days_until_due = _days_until(due_at)
    stage = "closed" if days_until_due is not None and days_until_due < 0 else "open"

    if str(source or "").upper() == "SAM" and naics and not nsn:
        procurement_scope = "service"
        classification_scheme = "NAICS"
        classification_value = naics
        sourcing_model = "service-provider"
    elif nsn or (fsc and str(source or "").upper() == "DIBBS"):
        procurement_scope = "product"
        classification_scheme = "NSN/FSC"
        classification_value = nsn or fsc
        sourcing_model = "manufacturer-distributor"
    elif naics:
        procurement_scope = "service"
        classification_scheme = "NAICS"
        classification_value = naics
        sourcing_model = "service-provider"
    else:
        procurement_scope = "mixed"
        classification_scheme = None
        classification_value = None
        sourcing_model = "mixed"

    buyer_family = (
        "DLA / DIBBS"
        if str(source or "").upper() == "DIBBS"
        else ("SAM.gov" if str(source or "").upper() == "SAM" else source)
    )
    buyer_name = _first_text(office, sub_agency, agency)
    place_of_performance = _first_text(
        service_signals.get("place_of_performance"),
        merged_fields.get("place_of_performance"),
        getattr(opp, "place_of_performance", None),
        place_of_performance_hint,
    )
    period_of_performance = _first_text(service_signals.get("period_of_performance"), merged_fields.get("period_of_performance"))
    response_type = _infer_response_type(source, submission_method, required_attachments, evaluation_factors)
    evaluation_basis = _infer_evaluation_basis(evaluation_factors, document_data.get("summary", {}).get("summary_text"))
    competition_type = "set_aside" if set_aside else ("full_and_open" if str(source or "").upper() == "SAM" else None)
    proposal_signal_count = len(required_attachments) + len(review_flags) + len(missing_information) + len(amendments)
    proposal_burden = _label_from_count(proposal_signal_count)
    submission_channel = (
        submission_method
        or submission_office
        or ("through the SAM notice contacts and solicitation attachments" if str(source or "").upper() == "SAM" else None)
        or ("through the DIBBS RFQ package" if str(source or "").upper() == "DIBBS" else None)
        or "not confirmed yet"
    )

    summary_parts = [
        _first_text(buyer_family, source),
        procurement_scope.title(),
        f"{classification_scheme} {classification_value}" if classification_scheme and classification_value else None,
        set_aside,
        f"Response: {response_type.replace('_', ' ').title()}" if str(source or "").upper() == "SAM" else None,
        f"Stage: {stage.title()}",
    ]

    return {
        "buyer_family": buyer_family,
        "buyer_name": buyer_name,
        "agency": agency,
        "sub_agency": sub_agency,
        "office": office,
        "procurement_scope": procurement_scope,
        "classification_scheme": classification_scheme,
        "classification_value": classification_value,
        "nsn": nsn,
        "fsc": fsc,
        "naics": naics,
        "set_aside": set_aside,
        "stage": stage,
        "competition_type": competition_type,
        "response_type": response_type,
        "evaluation_basis": evaluation_basis,
        "place_of_performance": place_of_performance,
        "period_of_performance": period_of_performance,
        "submission_channel": submission_channel,
        "submission_method": submission_method,
        "submission_office": submission_office,
        "contact_name": contact_name or _first_text(primary_contact.get("fullName")),
        "contact_email": contact_email or _first_text(primary_contact.get("email")),
        "sourcing_model": sourcing_model,
        "proposal_burden": proposal_burden,
        "required_attachment_count": len(required_attachments),
        "amendment_count": len(amendments),
        "evaluation_factor_count": len(evaluation_factors),
        "review_flag_count": len(review_flags),
        "missing_information_count": len(missing_information),
        "summary": " | ".join(part for part in summary_parts if part),
    }


def build_readiness_assessment(
    opp: Any,
    *,
    document_count: int = 0,
    vendor_count: int = 0,
    quote_count: int = 0,
    submission_package_count: int = 0,
    open_task_count: int = 0,
    has_nsn: bool = False,
    has_set_aside: bool = False,
    has_submission: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utcnow()
    due_at = getattr(opp, "due_at", None)
    days_until_due = _days_until(due_at, current)
    is_closed = days_until_due is not None and days_until_due < 0

    score = 0
    score += 20 if document_count > 0 else 0
    score += 20 if vendor_count > 0 else 0
    score += 20 if quote_count > 0 else 0
    score += 15 if submission_package_count > 0 else 0
    score += 10 if open_task_count > 0 else 0
    score += 10 if has_nsn else 0
    score += 5 if has_set_aside else 0
    score = min(score, 100)

    blockers: list[str] = []
    next_actions: list[str] = []

    if document_count == 0:
        blockers.append("RFQ package has not been downloaded or processed")
        next_actions.append("Open RFQ Package")
    if vendor_count == 0:
        blockers.append("No vendor candidates are attached yet")
        next_actions.append("Find suppliers")
    if quote_count == 0 and vendor_count > 0:
        blockers.append("No quote responses are recorded yet")
        next_actions.append("Send RFQs")
    if submission_package_count == 0 and quote_count > 0:
        blockers.append("Submission package has not been prepared")
        next_actions.append("Build submission package")
    if open_task_count == 0 and not is_closed:
        next_actions.append("Seed workspace tasks")

    if is_closed:
        state = "REFERENCE_ONLY"
        summary = "This solicitation is closed. Keep it as a research and award-intelligence record."
    elif quote_count > 0 and submission_package_count > 0:
        state = "READY_TO_SUBMIT" if days_until_due is None or days_until_due <= 5 else "READY_TO_WORK"
        summary = "Quotes and submission materials are in place. This opportunity can move forward."
    elif document_count == 0:
        state = "NEEDS_DOCUMENT_REVIEW"
        summary = "The opportunity still needs a processed RFQ package before the workspace is reliable."
    elif vendor_count == 0:
        state = "NEEDS_SUPPLIERS"
        summary = "The requirement is in the workspace, but supplier discovery still needs attention."
    elif quote_count == 0:
        state = "SOURCING_IN_PROGRESS"
        summary = "Vendor candidates exist, but pricing and quote coverage are still missing."
    elif submission_package_count == 0:
        state = "PREPARE_SUBMISSION"
        summary = "The opportunity has sourcing momentum and now needs a submission package."
    else:
        state = "READY_TO_WORK"
        summary = "Core documents, sourcing, and execution signals are all present."

    return {
        "score": score,
        "state": state,
        "summary": summary,
        "days_until_due": days_until_due,
        "blockers": blockers,
        "next_actions": list(dict.fromkeys(next_actions)),
        "signals": {
            "documents": document_count,
            "vendor_candidates": vendor_count,
            "quotes": quote_count,
            "submission_packages": submission_package_count,
            "open_tasks": open_task_count,
            "has_nsn": bool(has_nsn),
            "has_set_aside": bool(has_set_aside),
            "has_submission": bool(has_submission),
        },
    }
