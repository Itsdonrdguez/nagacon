from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_run import AgentType
from app.models.bid_submission import BidSubmission
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceTask
from app.services.provider_settings_service import get_effective_openai_api_key, get_effective_openai_model
from app.services.recommendation_engine import build_workspace_recommendation, upsert_recommendation_analysis
from app.services.research.usaspending_research_service import search_usaspending_for_opportunity
from app.services.workspace_service import build_research_profile, create_artifact, ensure_parsed, extract_solicitation_poc
from app.utils.solicitation_status import derive_solicitation_status


PHASE_AGENT_MAP: dict[str, list[str]] = {
    "phase_1": ["opportunity_analyst", "compliance_document", "vendor_research"],
    "phase_2": ["email_outreach"],
    "phase_3": ["proposal_workspace"],
}


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _artifact_payload(artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "content_json": artifact.content_json or {},
    }


def _agent_input_payload(opp: Opportunity) -> dict[str, Any]:
    return {
        "opportunity_id": opp.id,
        "source": opp.source,
        "solicitation_number": opp.solicitation_number,
        "title": getattr(opp, "display_title", None) or opp.title,
        "agency": opp.agency,
        "due_at": opp.due_at.isoformat() if opp.due_at else None,
    }


def _json_default(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _fallback_meta(reason: str, detail: str | None = None) -> dict[str, str]:
    return {
        "provider_status": "fallback",
        "fallback_reason": reason,
        "fallback_detail": detail or "",
    }


def _merge_json_like(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge_json_like(base.get(key), value)
        return merged
    if isinstance(base, list) and isinstance(override, list):
        return override if override else base
    return override if override is not None else base


def _normalize_label(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_text_requirements(text: str) -> tuple[list[str], list[str]]:
    upper = _safe_text(text).upper()
    requirements: list[str] = []
    vendor_asks: list[str] = []
    checks = [
        ("SMALL BUSINESS SET-ASIDE", "Small business set-aside language is present.", None),
        ("CERT.FOR NAT. DEF.", "National defense certification language is present.", "Confirm any certifications or representations required to quote."),
        ("PLEASE FURNISH QUOTATIONS", "Quote submission instructions are present in the solicitation.", "Confirm the correct quote submission channel and response format."),
        ("ISSUING OFFICE", "The issuing office is referenced in the solicitation.", "Confirm the exact issuing office or email/fax destination for the quote."),
        ("DELIVERY", "Delivery requirements are referenced in the solicitation.", "Provide lead time and delivery commitment for the requested quantity."),
        ("PACKAGING", "Packaging requirements may be present in the solicitation package.", "Confirm packaging or preservation requirements you can support."),
        ("FOB", "Shipping or FOB terms may be present in the solicitation package.", "Confirm shipping terms and any FOB assumptions in your quote."),
        ("URGENT", "Urgency language appears in the solicitation package.", "State whether you can meet the required turnaround timeline."),
    ]
    for needle, requirement, vendor_ask in checks:
        if needle in upper:
            requirements.append(requirement)
            if vendor_ask:
                vendor_asks.append(vendor_ask)
    return requirements, vendor_asks


def _first_regex_group(patterns: list[str], text: str, flags: int = re.IGNORECASE) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if not match:
            continue
        for group in match.groups():
            value = _normalize_label(group)
            if value:
                return value
    return None


def _format_nsn(value: str | None) -> str | None:
    digits = re.sub(r"\D+", "", _safe_text(value))
    if len(digits) == 13:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:]}"
    return _normalize_label(value) or None


def _extract_pdf_compliance_fields(text: str, source_file: str | None, source_file_type: str | None) -> dict[str, Any]:
    normalized = _safe_text(text)
    upper = normalized.upper()

    solicitation_number = _first_regex_group(
        [
            r"1\.\s*REQUEST\s+NO\.\s*([A-Z0-9-]{8,})",
            r"REFERENCE\s+NO\.\s+OF\s+DOCUMENT\s+BEING\s+CONTINUED:\s*(?:CONTINUED\s+ON\s+NEXT\s+PAGE\s*)?([A-Z0-9-]{8,})",
            r"\b(SPE[A-Z0-9-]{6,})\b",
            r"\b(SPE[A-Z0-9]{2,}\d[A-Z0-9]*)\b",
            r"\b(SP[A-Z0-9]{4,})\b",
            r"(?:SOLICITATION(?:\s+NUMBER)?|RFQ)\s*[:#]?\s*([A-Z0-9-]{6,})\b",
        ],
        normalized,
    )

    pr_number = _first_regex_group(
        [
            r"3\.\s*REQUISITION/PURCHASE\s+REQUEST\s+NO\.\s*(\d{6,})",
            r"\bPR(?:\s*(?:NO|NUMBER|#))?\s*[:#]?\s*(\d{6,})\b",
            r"\bPURCHASE\s+REQUEST(?:\s+NUMBER)?\s*[:#]?\s*(\d{6,})\b",
        ],
        normalized,
    )
    nsn = _format_nsn(_first_regex_group(
        [
            r"NSN/MATERIAL\s*:\s*(\d{13})",
            r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b",
            r"\bNSN\s*[:#]?\s*(\d{4}-\d{2}-\d{3}-\d{4})\b",
            r"\bNSN\s*[:#]?\s*(\d{13})\b",
        ],
        normalized,
    ))
    nomenclature = _first_regex_group(
        [
            r"ITEM\s+DESCRIPTION\s+([A-Z0-9,./() \-]{4,})",
            r"\bNOMENCLATURE\s*[:#]?\s*([A-Z0-9,./() \-]{4,})",
            r"\bITEM(?:\s+DESCRIPTION)?\s*[:#]?\s*([A-Z0-9,./() \-]{4,})",
        ],
        normalized,
    )
    if nomenclature:
        nomenclature = nomenclature.split("RA001:", 1)[0].split("UNIT OF ISSUE", 1)[0].splitlines()[0].strip(" -")
    quantity = _first_regex_group(
        [
            r"\bCLIN\s+PR\s+PRLI\s+UI\s+QUANTITY.*?\n\s*\d+\s+\d+\s+\d+\s+[A-Z]{2}\s+(\d+(?:\.\d+)?)",
            r"\bQUANTITY\s*[:#]?\s*(\d+(?:\.\d+)?)\b",
            r"\bQTY\s*[:#]?\s*(\d+(?:\.\d+)?)\b",
            r"\b(\d+(?:\.\d+)?)\s+(?:EA|EACH|BX|BOX|KT|SET|PK|PACK)\b",
        ],
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    unit_of_issue = _first_regex_group(
        [
            r"\bCLIN\s+PR\s+PRLI\s+UI\s+QUANTITY.*?\n\s*\d+\s+\d+\s+\d+\s+([A-Z]{2})\s+\d+(?:\.\d+)?",
            r"\bUNIT OF ISSUE\s*[:#]?\s*([A-Z]{1,6})\b",
        ],
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return_by = _first_regex_group(
        [
            r"15\.\s*Date\s+of\s+Quotation.*?(20\d{2}\s+[A-Z]{3}\s+\d{2})",
            r"\bRETURN\s+BY(?:\s+DATE)?\s*[:#]?\s*([0-9]{2}-[0-9]{2}-[0-9]{4})\b",
            r"BEFORE\s+CLOSE\s+OF\s+BUSINESS\s*\(Date\).*?(\d{4}\s+[A-Z]{3}\s+\d{2})",
            r"\bBEFORE\s+CLOSE\s+OF\s+BUSINESS\s*\(?DATE\)?\s*([0-9]{2}-[0-9]{2}-[0-9]{4})\b",
            r"\bCLOSE\s+OF\s+BUSINESS\s*\(?DATE\)?\s*([0-9]{2}-[0-9]{2}-[0-9]{4})\b",
        ],
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    issue_date = _first_regex_group(
        [
            r"2\.\s*DATE\s+ISSUED\s*(\d{4}\s+[A-Z]{3}\s+\d{2})",
            r"\bISSUE(?:D)?\s+DATE\s*[:#]?\s*([0-9]{2}-[0-9]{2}-[0-9]{4})\b",
            r"\bDATE\s+ISSUED\s*[:#]?\s*([0-9]{2}-[0-9]{2}-[0-9]{4})\b",
        ],
        normalized,
    )
    delivery_days = _first_regex_group(
        [
            r"DELIVERY\s*\(IN DAYS\)\s*:?\s*0*([0-9]{1,4})",
            r"\bDELIVERY\s*[:#]?\s*0*([0-9]{1,4})\s*DAYS\b",
        ],
        normalized,
    )
    set_aside_hint = None
    if "IS NOT A SMALL BUSINESS SET-ASIDE" in upper:
        set_aside_hint = "Not a Small Business Set-Aside"
    elif "SMALL BUSINESS SET-ASIDE" in upper:
        set_aside_hint = "Small Business Set-Aside"

    packaging_standard = _first_regex_group(
        [
            r"\b(MIL-STD-\d+[A-Z0-9.-]*)\b",
            r"\b(ASTM\s+[A-Z0-9.-]+)\b",
        ],
        normalized,
    )
    medical_marking_hint = _first_regex_group(
        [
            r"(MEDICAL MARKING STANDARD NO\.?\s*\d+)",
        ],
        normalized,
    )
    fob_terms = None
    if "FOB DESTINATION" in upper:
        fob_terms = "FOB Destination"
    elif "FOB ORIGIN" in upper:
        fob_terms = "FOB Origin"
    elif re.search(r"\bFOB\b", upper):
        fob_terms = _first_regex_group(
            [
                r"\bFOB\s*[:#]?\s*([A-Z][A-Z /-]{2,30})",
            ],
            normalized,
        ) or "FOB terms referenced in the RFQ"
    source_and_part_number_required = "SPECIFY SOURCE AND PART NUMBER" in upper
    certification_required = "CERT.FOR NAT. DEF." in upper
    fda_regulated_hint = bool(re.search(r"\bFDA\b", upper))
    submission_method = None
    if "DIBBS" in upper:
        submission_method = "through DIBBS or the issuing office listed in the RFQ"
    elif "PLEASE FURNISH QUOTATIONS TO THE ISSUING OFFICE" in upper:
        submission_method = "to the issuing office listed in the RFQ"

    poc = extract_solicitation_poc(normalized)
    buyer_name_match = re.search(r"Name:\s*([A-Za-z][A-Za-z .'-]+)\s+Buyer\s+Code:", normalized, re.IGNORECASE)
    buyer_phone_match = re.search(r"Tel:\s*([0-9(). -]{10,})", normalized, re.IGNORECASE)
    buyer_email_match = re.search(r"Email:\s*([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", normalized, re.IGNORECASE)
    issued_by_match = re.search(
        r"RATING\s+(.*?)\s+Name:\s*[A-Za-z]",
        normalized,
        re.IGNORECASE | re.DOTALL,
    )
    issued_by = None
    if issued_by_match:
        issued_by = " | ".join(
            line.strip(" :\t")
            for line in issued_by_match.group(1).splitlines()
            if line.strip()
        )
    clauses_or_requirements = [
        "National defense certification language present." if "CERT.FOR NAT. DEF." in upper else None,
        "Quote response deadline language present." if "PLEASE FURNISH QUOTATIONS" in upper else None,
        "Delivery terms are referenced in the solicitation." if re.search(r"\bDELIVERY\b", upper) else None,
        "Packaging requirements may be present in the solicitation." if re.search(r"\bPACKAGING\b", upper) else None,
        "Shipping or FOB terms may be present in the solicitation." if re.search(r"\bFOB\b", upper) else None,
    ]

    return {
        "nsn": nsn,
        "nomenclature": nomenclature,
        "solicitation_number": solicitation_number,
        "pr_number": pr_number,
        "quantity": quantity,
        "unit_of_issue": unit_of_issue,
        "return_by": return_by,
        "issue_date": issue_date,
        "delivery_days": delivery_days,
        "source_file": source_file,
        "source_file_type": source_file_type,
        "set_aside_hint": set_aside_hint,
        "submission_method": submission_method,
        "submission_office_hint": issued_by or poc.get("submission_office") or ("Issuing office shown in the solicitation document." if "PLEASE FURNISH QUOTATIONS TO THE ISSUING OFFICE" in upper else None),
        "solicitation_contact_name": _normalize_label(buyer_name_match.group(1) if buyer_name_match else poc.get("contact_name")),
        "solicitation_contact_email": _normalize_label(buyer_email_match.group(1) if buyer_email_match else poc.get("email")),
        "solicitation_contact_phone": _normalize_label(buyer_phone_match.group(1) if buyer_phone_match else poc.get("phone")),
        "packaging_standard": packaging_standard,
        "medical_marking_hint": medical_marking_hint,
        "fob_terms": fob_terms,
        "source_and_part_number_required": source_and_part_number_required,
        "certification_required": certification_required,
        "fda_regulated_hint": fda_regulated_hint,
        "clauses_or_requirements": [item for item in clauses_or_requirements if item],
    }


def _build_extracted_facts_from_pdf(compliance_fields: dict[str, Any]) -> list[dict[str, str]]:
    facts = [
        {"label": "NSN", "value": _normalize_label(compliance_fields.get("nsn"))},
        {"label": "Nomenclature", "value": _normalize_label(compliance_fields.get("nomenclature"))},
        {"label": "Solicitation", "value": _normalize_label(compliance_fields.get("solicitation_number"))},
        {"label": "PR Number", "value": _normalize_label(compliance_fields.get("pr_number"))},
        {
            "label": "Quantity",
            "value": _normalize_label(
                " ".join(
                    item
                    for item in [
                        _normalize_label(compliance_fields.get("quantity")),
                        _normalize_label(compliance_fields.get("unit_of_issue")),
                    ]
                    if item
                )
            ),
        },
        {"label": "Return By", "value": _normalize_label(compliance_fields.get("return_by"))},
        {"label": "Issue Date", "value": _normalize_label(compliance_fields.get("issue_date"))},
        {
            "label": "Delivery",
            "value": (
                f"{_normalize_label(compliance_fields.get('delivery_days'))} days ADO"
                if _normalize_label(compliance_fields.get("delivery_days"))
                else None
            ),
        },
        {"label": "Submission Method", "value": _normalize_label(compliance_fields.get("submission_method"))},
        {"label": "Buyer", "value": _normalize_label(compliance_fields.get("solicitation_contact_name"))},
        {"label": "Contact Email", "value": _normalize_label(compliance_fields.get("solicitation_contact_email"))},
        {"label": "Contact Phone", "value": _normalize_label(compliance_fields.get("solicitation_contact_phone"))},
        {"label": "Source File", "value": _normalize_label(compliance_fields.get("source_file"))},
    ]
    return [fact for fact in facts if fact["value"]]


def _build_pdf_required_actions(compliance_fields: dict[str, Any], combined_preview: str) -> list[str]:
    actions: list[str] = []
    quantity = _normalize_label(compliance_fields.get("quantity"))
    unit_of_issue = _normalize_label(compliance_fields.get("unit_of_issue"))
    return_by = _normalize_label(compliance_fields.get("return_by"))
    delivery_days = _normalize_label(compliance_fields.get("delivery_days"))
    submission_method = _normalize_label(compliance_fields.get("submission_method"))
    submission_office = _normalize_label(compliance_fields.get("submission_office_hint"))
    packaging_standard = _normalize_label(compliance_fields.get("packaging_standard"))
    medical_marking_hint = _normalize_label(compliance_fields.get("medical_marking_hint"))
    fob_terms = _normalize_label(compliance_fields.get("fob_terms"))

    if return_by:
        destination = submission_method or submission_office or "through the channel identified in the RFQ"
        actions.append(f"Submit the quote {destination} by {return_by}.")
    if quantity:
        actions.append(f"Quote the requested quantity of {quantity}{f' {unit_of_issue}' if unit_of_issue else ''}.")
    if delivery_days:
        actions.append(f"Confirm delivery within {delivery_days} days ADO.")
    elif re.search(r"\bDELIVERY\b", combined_preview.upper()):
        actions.append("Confirm the delivery schedule stated in the RFQ.")
    if compliance_fields.get("source_and_part_number_required"):
        actions.append("State the source and part number being supplied in the quote.")
    if packaging_standard:
        actions.append(f"Meet the packaging requirement identified in the RFQ ({packaging_standard}).")
    elif re.search(r"\bPACKAGING\b", combined_preview.upper()):
        actions.append("Review the RFQ packaging language and confirm the exact packaging standard before submission.")
    if medical_marking_hint:
        actions.append(f"Follow {medical_marking_hint} for the shipped item.")
    if fob_terms:
        actions.append(f"Quote using the RFQ shipping term: {fob_terms}.")
    if compliance_fields.get("certification_required"):
        actions.append("Review and satisfy the national defense certification language included in the RFQ.")
    if compliance_fields.get("fda_regulated_hint"):
        actions.append("Confirm any FDA-related product compliance or regulatory support required for the item.")

    deduped: list[str] = []
    for item in actions:
        clean = _normalize_label(item)
        if clean and clean not in deduped:
            deduped.append(clean)
    return deduped


def _build_pdf_review_flags(compliance_fields: dict[str, Any], combined_preview: str) -> list[str]:
    review_flags: list[str] = []
    upper = combined_preview.upper()
    if not compliance_fields.get("return_by"):
        review_flags.append("The response deadline could not be confirmed from the extracted document text.")
    if not compliance_fields.get("submission_office_hint") and not compliance_fields.get("solicitation_contact_email"):
        review_flags.append("The submission destination is not explicit enough yet; confirm the office or email before sending a quote.")
    if "PACKAGING" in upper and not compliance_fields.get("packaging_standard"):
        review_flags.append("Packaging language appears in the RFQ, but the exact packaging standard could not be isolated from the extracted text.")
    if "FOB" in upper and not compliance_fields.get("fob_terms"):
        review_flags.append("FOB language appears in the RFQ, but the exact FOB term could not be isolated from the extracted text.")
    if not compliance_fields.get("solicitation_contact_name") and not compliance_fields.get("solicitation_contact_email"):
        review_flags.append("Buyer contact details are incomplete in the extracted document output and should be confirmed.")

    deduped: list[str] = []
    for item in review_flags:
        clean = _normalize_label(item)
        if clean and clean not in deduped:
            deduped.append(clean)
    return deduped


def _build_pdf_missing_information(compliance_fields: dict[str, Any], combined_preview: str) -> list[str]:
    missing: list[str] = []
    if not compliance_fields.get("nsn"):
        missing.append("NSN was not extracted from the available source text.")
    if not compliance_fields.get("nomenclature"):
        missing.append("Item nomenclature or description needs confirmation from the source package.")
    if not compliance_fields.get("quantity"):
        missing.append("Requested quantity is not clearly extracted yet.")
    if not compliance_fields.get("return_by"):
        missing.append("Return-by date or due date needs confirmation from the solicitation.")
    if "PLEASE FURNISH QUOTATIONS TO THE ISSUING OFFICE" in combined_preview.upper() and "@" not in combined_preview and "FAX" not in combined_preview.upper():
        missing.append("Submission destination is referenced, but the exact office/email/fax should be confirmed from the document.")
    if not compliance_fields.get("source_file"):
        missing.append("No downloaded solicitation file is available for document-grounded review.")
    deduped: list[str] = []
    for item in missing:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _build_vendor_request_items_from_pdf(compliance_fields: dict[str, Any], combined_preview: str) -> list[str]:
    asks = [
        "Provide unit pricing for the requested item.",
        "Confirm available quantity and current lead time.",
        "Confirm your part number and CAGE code for the quoted item.",
    ]
    if compliance_fields.get("nsn"):
        asks.append(f"Confirm that your quote supports NSN {compliance_fields.get('nsn')}.")
    if compliance_fields.get("quantity"):
        asks.append(f"Confirm ability to supply quantity {compliance_fields.get('quantity')}.")
    if compliance_fields.get("return_by"):
        asks.append(f"Confirm whether you can support the return-by timeline of {compliance_fields.get('return_by')}.")
    _, text_asks = _extract_text_requirements(combined_preview)
    asks.extend(text_asks)
    deduped: list[str] = []
    for item in asks:
        clean = _normalize_label(item)
        if clean and clean not in deduped:
            deduped.append(clean)
    return deduped


def _load_submission_context(db: Session, opp: Opportunity) -> tuple[BidSubmission | None, VendorQuote | None]:
    submission = db.query(BidSubmission).filter(BidSubmission.opportunity_id == opp.id).first()
    planned_quote = None
    if submission and submission.planned_vendor_quote_id:
        planned_quote = db.query(VendorQuote).filter(VendorQuote.id == submission.planned_vendor_quote_id).first()
    if not planned_quote and submission and submission.planned_vendor_cage:
        planned_quote = (
            db.query(VendorQuote)
            .filter(VendorQuote.opportunity_id == opp.id, VendorQuote.cage == submission.planned_vendor_cage)
            .order_by(VendorQuote.updated_at.desc())
            .first()
        )
    return submission, planned_quote


def _openai_json_enrich(
    *,
    db: Session,
    user_id: int | None = None,
    system_prompt: str,
    user_context: dict[str, Any],
    fallback_output: dict[str, Any],
    model_name: str | None = None,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    api_key = get_effective_openai_api_key(db, user_id=user_id) or getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return fallback_output, "deterministic_fallback", _fallback_meta("missing_openai_key", "Add a valid OpenAI API key in Settings.")

    try:
        from openai import OpenAI  # type: ignore
        from openai import APIConnectionError, AuthenticationError, PermissionDeniedError, RateLimitError  # type: ignore
    except Exception:
        return fallback_output, "deterministic_fallback", _fallback_meta("missing_openai_sdk", "Install the OpenAI SDK in the backend environment.")

    prompt = (
        "Return valid JSON only. Preserve the same top-level keys as the fallback structure.\n\n"
        f"Context:\n{json.dumps(user_context, indent=2, default=_json_default)}\n\n"
        f"Fallback JSON shape:\n{json.dumps(fallback_output, indent=2, default=_json_default)}"
    )
    model = model_name or get_effective_openai_model(db, user_id=user_id) or getattr(settings, "OPENAI_PROPOSAL_MODEL", "gpt-4o-mini")

    try:
        client = OpenAI(
            api_key=api_key,
            http_client=httpx.Client(trust_env=False, timeout=60.0),
        )
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        raw = response.choices[0].message.content or ""
        if not raw.strip():
            return fallback_output, "deterministic_fallback", _fallback_meta("empty_openai_response", "OpenAI returned an empty response.")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return fallback_output, "deterministic_fallback", _fallback_meta("invalid_openai_json", "OpenAI returned non-JSON output.")
        return _merge_json_like(fallback_output, parsed), model, {"provider_status": "openai"}
    except RateLimitError as exc:
        return fallback_output, "deterministic_fallback", _fallback_meta("openai_quota_exceeded", str(exc))
    except AuthenticationError as exc:
        return fallback_output, "deterministic_fallback", _fallback_meta("openai_auth_failed", str(exc))
    except PermissionDeniedError as exc:
        return fallback_output, "deterministic_fallback", _fallback_meta("openai_permission_denied", str(exc))
    except APIConnectionError as exc:
        return fallback_output, "deterministic_fallback", _fallback_meta("openai_connection_error", str(exc))
    except httpx.HTTPError as exc:
        return fallback_output, "deterministic_fallback", _fallback_meta("openai_http_error", str(exc))
    except Exception as exc:
        return fallback_output, "deterministic_fallback", _fallback_meta("openai_unknown_error", str(exc))


def _run_opportunity_analyst(db: Session, opp: Opportunity, *, user_id: int | None = None) -> dict[str, Any]:
    parsed = ensure_parsed(db, opp)
    profile = build_research_profile(opp, parsed)
    submission, planned_quote = _load_submission_context(db, opp)
    recommendation_snapshot = build_workspace_recommendation(db, opp, parsed=parsed, submission=submission)
    due_status = derive_solicitation_status(opp.due_at)
    risks = []
    if not profile.get("nsn"):
        risks.append("NSN not extracted yet.")
    if not profile.get("approved_source_count"):
        risks.append("Approved sources not identified yet.")
    if due_status == "CLOSED":
        risks.append("Solicitation is closed and should be treated as research-only.")

    fallback_output = {
        "phase": "phase_1",
        "agent_key": "opportunity_analyst",
        "summary": {
            "title": profile.get("title"),
            "source": profile.get("source"),
            "agency": profile.get("agency"),
            "solicitation_status": profile.get("solicitation_status"),
        },
        "executive_assessment": recommendation_snapshot.get("summary")
        or (
            f"{profile.get('title') or opp.title} is a {profile.get('source') or opp.source} opportunity "
            f"for {profile.get('agency') or 'the agency'} with status {profile.get('solicitation_status') or due_status}."
        ),
        "recommendation": recommendation_snapshot.get("recommendation"),
        "recommendation_score": recommendation_snapshot.get("recommendation_score"),
        "confidence": recommendation_snapshot.get("confidence"),
        "score_breakdown": recommendation_snapshot.get("score_breakdown"),
        "reasons": recommendation_snapshot.get("reasons"),
        "strengths": recommendation_snapshot.get("strengths"),
        "blockers": recommendation_snapshot.get("blockers"),
        "bid_posture": recommendation_snapshot.get("bid_posture") or ("research_only" if due_status == "CLOSED" else "evaluate_to_bid"),
        "research_profile": profile,
        "workspace_signals": recommendation_snapshot.get("workspace_signals"),
        "planned_vendor": {
            "company_name": getattr(submission, "planned_vendor_name", None) or getattr(planned_quote, "company_name", None),
            "cage": getattr(submission, "planned_vendor_cage", None) or getattr(planned_quote, "cage", None),
            "unit_price": float(planned_quote.unit_price) if planned_quote and planned_quote.unit_price is not None else None,
            "lead_time_days": getattr(planned_quote, "lead_time_days", None),
        },
        "risks": list(dict.fromkeys(risks + list(recommendation_snapshot.get("blockers") or []))),
        "gaps": [
            "Detailed compliance requirements need confirmation from documents." if not profile.get("text_source") else None,
            "Vendor coverage should be expanded if only limited approved sources are available." if (profile.get("approved_source_count") or 0) < 2 else None,
        ],
        "recommended_next_actions": recommendation_snapshot.get("next_actions") or profile.get("recommended_actions", []),
        "recommendation_snapshot": recommendation_snapshot,
        "generated_at": datetime.utcnow().isoformat(),
    }
    fallback_output["gaps"] = [item for item in fallback_output["gaps"] if item]
    context = {
        "opportunity": _agent_input_payload(opp),
        "research_profile": profile,
        "parsed_json": parsed,
        "recommendation_snapshot": recommendation_snapshot,
        "submission": {
            "status": getattr(submission, "status", None),
            "planned_vendor_name": getattr(submission, "planned_vendor_name", None),
            "planned_vendor_cage": getattr(submission, "planned_vendor_cage", None),
        },
        "risk_seed": risks,
    }
    output, model_name, provider_meta = _openai_json_enrich(
        db=db,
        user_id=user_id,
        system_prompt=(
            "You are an opportunity analyst for a government contracting workspace. "
            "Produce a concise, evidence-based analysis with clear risks, gaps, bid posture, and next actions."
        ),
        user_context=context,
        fallback_output=fallback_output,
    )
    for key in [
        "recommendation",
        "recommendation_score",
        "confidence",
        "score_breakdown",
        "reasons",
        "strengths",
        "blockers",
        "workspace_signals",
        "bid_posture",
    ]:
        output[key] = recommendation_snapshot.get(key)
    output["recommended_next_actions"] = recommendation_snapshot.get("next_actions") or output.get("recommended_next_actions") or []
    output["recommendation_snapshot"] = recommendation_snapshot
    output["executive_assessment"] = output.get("executive_assessment") or recommendation_snapshot.get("summary")
    output["risks"] = list(dict.fromkeys((output.get("risks") or []) + list(recommendation_snapshot.get("blockers") or [])))
    output["gaps"] = list(dict.fromkeys((output.get("gaps") or []) + list(recommendation_snapshot.get("blockers") or [])))[:8]
    output["generated_at"] = output.get("generated_at") or datetime.utcnow().isoformat()
    output["model_name"] = model_name
    output.update(provider_meta)
    upsert_recommendation_analysis(db, opp.id, recommendation_snapshot, ai_summary=output.get("executive_assessment"))
    artifact = create_artifact(
        db,
        opp.id,
        "OPPORTUNITY_ANALYSIS",
        f"Opportunity Analyst - {opp.solicitation_number or opp.id}",
        content_json=output,
        replace_existing=True,
    )
    return {"output": output, "artifact": _artifact_payload(artifact), "model_name": model_name, **provider_meta}


def _run_compliance_document_agent(db: Session, opp: Opportunity, *, user_id: int | None = None) -> dict[str, Any]:
    parsed = ensure_parsed(db, opp)
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    ranked_files = sorted(
        files,
        key=lambda file: (
            0 if _safe_text(getattr(file, "extracted_text", None)) else 1,
            0 if bool(getattr(file, "parsed_metadata", None) or {}) else 1,
            -(getattr(file, "created_at", None).timestamp() if getattr(file, "created_at", None) else 0),
        ),
    )
    document_insights = []
    for file in ranked_files[:5]:
        parsed_metadata = getattr(file, "parsed_metadata", None) or {}
        extracted_text = _safe_text(getattr(file, "extracted_text", None))
        document_insights.append({
            "file_id": file.id,
            "filename": file.filename,
            "file_type": file.file_type,
            "has_parsed_metadata": bool(parsed_metadata),
            "has_extracted_text": bool(extracted_text),
            "parsed_keys": sorted(list(parsed_metadata.keys()))[:12],
            "text_preview": extracted_text[:500] if extracted_text else "",
        })

    source_file = document_insights[0]["filename"] if document_insights else None
    source_file_type = document_insights[0]["file_type"] if document_insights else None
    primary_text = _safe_text(getattr(ranked_files[0], "extracted_text", None)) if ranked_files else ""
    combined_preview = " ".join(
        _safe_text(getattr(file, "extracted_text", None))
        for file in ranked_files
        if _safe_text(getattr(file, "extracted_text", None))
    )[:6000]
    text_requirements, text_vendor_asks = _extract_text_requirements(combined_preview)
    compliance_fields = _extract_pdf_compliance_fields(
        primary_text or combined_preview,
        source_file=source_file,
        source_file_type=source_file_type,
    )
    extracted_facts = _build_extracted_facts_from_pdf(compliance_fields)
    required_actions = _build_pdf_required_actions(compliance_fields, combined_preview)
    missing_information = _build_pdf_missing_information(compliance_fields, combined_preview)
    review_flags = _build_pdf_review_flags(compliance_fields, combined_preview)
    vendor_request_items = _build_vendor_request_items_from_pdf(compliance_fields, combined_preview)

    fallback_output = {
        "phase": "phase_1",
        "agent_key": "compliance_document",
        "document_count": len(files),
        "document_insights": document_insights,
        "source_basis": "pdf_document_extraction",
        "compliance_fields": compliance_fields,
        "extracted_facts": extracted_facts,
        "parsed_summary": {
            "nsn": parsed.get("nsn"),
            "nomenclature": parsed.get("nomenclature") or parsed.get("item_description"),
            "solicitations": [],
            "text_source": parsed.get("text_source") or {},
        },
        "required_actions": required_actions or text_requirements,
        "submission_requirements": required_actions or text_requirements,
        "document_findings": [
            f"{file['filename']} contains extracted text ready for review." for file in document_insights if file.get("has_extracted_text")
        ][:5],
        "missing_documents": [] if files else ["No downloaded documents are available yet."],
        "missing_information": missing_information,
        "review_flags": review_flags,
        "vendor_request_items": vendor_request_items + text_vendor_asks,
        "risks": [
            "Document extraction may be incomplete for scanned or image-based PDFs." if files else "No files have been downloaded for compliance review yet."
        ] + review_flags,
        "generated_at": datetime.utcnow().isoformat(),
    }
    fallback_output["submission_requirements"] = list(dict.fromkeys([item for item in fallback_output["submission_requirements"] if item]))
    fallback_output["required_actions"] = list(dict.fromkeys([item for item in fallback_output["required_actions"] if item]))
    fallback_output["vendor_request_items"] = list(dict.fromkeys([item for item in fallback_output["vendor_request_items"] if item]))
    fallback_output["review_flags"] = list(dict.fromkeys([item for item in fallback_output["review_flags"] if item]))
    fallback_output["risks"] = list(dict.fromkeys([item for item in fallback_output["risks"] if item]))
    context = {
        "opportunity": _agent_input_payload(opp),
        "pdf_text_excerpt": (primary_text or combined_preview)[:3000],
        "document_insights": document_insights,
        "extracted_facts": extracted_facts,
        "compliance_fields": compliance_fields,
        "required_actions": fallback_output["required_actions"],
        "missing_information": missing_information,
        "review_flags": fallback_output["review_flags"],
        "vendor_request_items": fallback_output["vendor_request_items"],
    }
    output, model_name, provider_meta = _openai_json_enrich(
        db=db,
        user_id=user_id,
        system_prompt=(
            "You are a compliance and document review analyst for government solicitations. "
            "Use only the provided PDF-derived document text and document insights. "
            "Do not infer compliance facts from external opportunity metadata. "
            "Summarize document findings, likely submission requirements, missing information, practical compliance risks, and the vendor quote items that should be requested from outreach."
        ),
        user_context=context,
        fallback_output=fallback_output,
    )
    output["generated_at"] = output.get("generated_at") or datetime.utcnow().isoformat()
    output["model_name"] = model_name
    output.update(provider_meta)
    artifact = create_artifact(
        db,
        opp.id,
        "COMPLIANCE_BRIEF",
        f"Compliance Brief - {opp.solicitation_number or opp.id}",
        content_json=output,
    )
    return {"output": output, "artifact": _artifact_payload(artifact), "model_name": model_name, **provider_meta}


def _run_vendor_research_agent(db: Session, opp: Opportunity) -> dict[str, Any]:
    research = search_usaspending_for_opportunity(opp, db=db)
    leads = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opp.id)
        .order_by(VendorLead.confidence.desc())
        .all()
    )
    top_leads = [
        {
            "id": lead.id,
            "company_name": lead.company_name,
            "cage": lead.cage,
            "status": lead.status,
            "confidence": lead.confidence,
            "source_type": lead.source_type,
            "notes": lead.notes,
        }
        for lead in leads[:10]
    ]
    output = {
        "phase": "phase_1",
        "agent_key": "vendor_research",
        "top_workspace_leads": top_leads,
        "likely_vendors": (research.get("likely_vendors") or [])[:8],
        "research_profile": research.get("research_profile") or {},
        "query_debug": research.get("query_debug") or [],
        "generated_at": datetime.utcnow().isoformat(),
    }
    artifact = create_artifact(
        db,
        opp.id,
        "VENDOR_RESEARCH",
        f"Vendor Research - {opp.solicitation_number or opp.id}",
        content_json=output,
    )
    return {"output": output, "artifact": _artifact_payload(artifact)}


def _run_email_outreach_agent(db: Session, opp: Opportunity, *, user_id: int | None = None) -> dict[str, Any]:
    parsed = ensure_parsed(db, opp)
    submission, planned_quote = _load_submission_context(db, opp)
    leads = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opp.id)
        .order_by(VendorLead.confidence.desc())
        .all()
    )
    target_vendors = [
        {
            "company_name": lead.company_name,
            "cage": lead.cage,
            "status": lead.status,
            "confidence": lead.confidence,
        }
        for lead in leads[:5]
    ]
    if planned_quote:
        planned_vendor_payload = {
            "company_name": planned_quote.company_name or getattr(submission, "planned_vendor_name", None),
            "cage": planned_quote.cage or getattr(submission, "planned_vendor_cage", None),
            "status": planned_quote.status,
            "confidence": 100,
            "email": planned_quote.email,
            "lead_time_days": planned_quote.lead_time_days,
            "unit_price": float(planned_quote.unit_price) if planned_quote.unit_price is not None else None,
        }
        target_vendors = [
            planned_vendor_payload,
            *[
                item for item in target_vendors
                if not (
                    _safe_text(item.get("cage")) == _safe_text(planned_vendor_payload.get("cage"))
                    and _safe_text(item.get("company_name")) == _safe_text(planned_vendor_payload.get("company_name"))
                )
            ],
        ]
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    extracted_file = next((file for file in files if _safe_text(getattr(file, "extracted_text", None))), None)
    extracted_preview = _safe_text(getattr(extracted_file, "extracted_text", None))[:500] if extracted_file else ""
    solicitation_row = ((parsed.get("solicitations") or [None])[0]) or {}
    nomenclature = parsed.get("item_description") or parsed.get("nomenclature") or getattr(opp, "display_title", None) or opp.title
    due_value = solicitation_row.get("return_by_date") or (opp.due_at.isoformat() if opp.due_at else None)
    vendor_request_items = _build_vendor_request_items(parsed, solicitation_row, extracted_preview)
    poc = extract_solicitation_poc(extracted_preview or getattr(opp, "raw_text", None))
    document_signals = []
    if parsed.get("nsn"):
        document_signals.append(f"NSN {parsed.get('nsn')}")
    if solicitation_row.get("qty"):
        document_signals.append(f"Quantity {solicitation_row.get('qty')}")
    if due_value:
        document_signals.append(f"Return by {due_value}")
    if solicitation_row.get("pr_number"):
        document_signals.append(f"PR {solicitation_row.get('pr_number')}")
    if solicitation_row.get("solicitation_number"):
        document_signals.append(f"Solicitation {solicitation_row.get('solicitation_number')}")
    if extracted_preview:
        document_signals.append("Document text preview was used to ground the draft")
    if poc.get("email"):
        document_signals.append(f"Solicitation POC email {poc.get('email')}")
    if poc.get("phone"):
        document_signals.append(f"Solicitation POC phone {poc.get('phone')}")
    contact_hint = []
    if poc.get("contact_name"):
        contact_hint.append(f"POC {poc.get('contact_name')}")
    if poc.get("email"):
        contact_hint.append(f"email {poc.get('email')}")
    if poc.get("phone"):
        contact_hint.append(f"phone {poc.get('phone')}")
    if poc.get("submission_office"):
        contact_hint.append(f"office {poc.get('submission_office')}")
    outreach_steps = [
        "Review target vendors and confirm the best outreach candidate.",
        "Generate or refine a targeted email draft artifact.",
        "Send outreach and log quote expectations, lead time, and pricing gaps.",
    ]
    recommended_target = target_vendors[0] if target_vendors else None
    fallback_output = {
        "phase": "phase_2",
        "agent_key": "email_outreach",
        "target_vendors": target_vendors,
        "nsn": parsed.get("nsn"),
        "solicitation_number": opp.solicitation_number,
        "recommended_target_vendor": recommended_target,
        "target_vendor_name": recommended_target.get("company_name") if recommended_target else None,
        "target_vendor_cage": recommended_target.get("cage") if recommended_target else None,
        "planned_vendor_preferred": bool(submission and (submission.planned_vendor_name or submission.planned_vendor_cage)),
        "subject": f"Quote Request: {opp.solicitation_number or opp.id} {getattr(opp, 'display_title', None) or opp.title}".strip(),
        "body": (
            f"Hello,\n\nWe are requesting a quote for solicitation {opp.solicitation_number or opp.id} regarding {nomenclature}.\n"
            f"- NSN: {parsed.get('nsn') or '[NSN]'}\n"
            f"- Quantity: {solicitation_row.get('qty') or '[QTY]'}\n"
            f"- Return By: {due_value or '[DUE DATE]'}\n"
            + (f"- Solicitation Contact: {' | '.join(contact_hint)}\n" if contact_hint else "")
            + "\n"
            "Please review the solicitation context below and respond with the requested quote details:\n"
            + "".join(f"- {item}\n" for item in vendor_request_items)
            + (f"\nDocument preview:\n{extracted_preview}\n" if extracted_preview else "\n")
            + "\nThank you."
        ),
        "vendor_request_items": vendor_request_items,
        "outreach_steps": outreach_steps,
        "follow_up_plan": [
            "Send the initial quote request to the highest-confidence vendor.",
            "Log pricing, lead time, and any missing technical details.",
            "Follow up with alternates if no response is received within one business day.",
        ],
        "document_context": {
            "source_file": getattr(extracted_file, "filename", None),
            "extracted_preview": extracted_preview,
            "solicitation_row": solicitation_row,
            "document_signals": document_signals,
        },
        "solicitation_poc": poc,
        "generated_at": datetime.utcnow().isoformat(),
    }
    context = {
        "opportunity": _agent_input_payload(opp),
        "parsed_json": parsed,
        "target_vendors": target_vendors,
        "submission": {
            "status": getattr(submission, "status", None),
            "planned_vendor_name": getattr(submission, "planned_vendor_name", None),
            "planned_vendor_cage": getattr(submission, "planned_vendor_cage", None),
        },
        "document_context": fallback_output["document_context"],
        "recommended_target_vendor": recommended_target,
        "vendor_request_items": vendor_request_items,
    }
    output, model_name, provider_meta = _openai_json_enrich(
        db=db,
        user_id=user_id,
        system_prompt=(
            "You are a vendor outreach specialist for government contracting. "
            "Create a practical outreach recommendation with a professional quote-request subject, body, target vendor suggestion, follow-up plan, and explicit requested quote items. "
            "Keep the output grounded in the solicitation context and preserve the provided document_context and vendor_request_items fields."
        ),
        user_context=context,
        fallback_output=fallback_output,
    )
    output["generated_at"] = output.get("generated_at") or datetime.utcnow().isoformat()
    output["model_name"] = model_name
    output.update(provider_meta)
    artifact = create_artifact(
        db,
        opp.id,
        "OUTREACH_PLAN",
        f"Outreach Plan - {opp.solicitation_number or opp.id}",
        content_json=output,
    )
    return {"output": output, "artifact": _artifact_payload(artifact), "model_name": model_name, **provider_meta}


def _run_proposal_workspace_agent(db: Session, opp: Opportunity) -> dict[str, Any]:
    submission, planned_quote = _load_submission_context(db, opp)
    tasks = (
        db.query(WorkspaceTask)
        .filter(WorkspaceTask.opportunity_id == opp.id)
        .order_by(WorkspaceTask.created_at.desc())
        .all()
    )
    open_tasks = [task for task in tasks if _safe_text(task.status).upper() != "DONE"]
    execution_plan = {
        "phase": "phase_3",
        "agent_key": "proposal_workspace",
        "open_task_count": len(open_tasks),
        "open_tasks": [
            {
                "task_type": task.task_type,
                "status": task.status,
                "due_at": task.due_at.isoformat() if task.due_at else None,
                "notes": task.notes,
            }
            for task in open_tasks[:10]
        ],
        "recommended_sequence": [
            "Finalize opportunity analysis and document review.",
            "Lock the shortlist and send targeted vendor outreach.",
            "Collect quote responses and update pricing assumptions.",
            "Prepare the submission package and final execution notes.",
        ],
        "planned_vendor": {
            "company_name": getattr(submission, "planned_vendor_name", None) or getattr(planned_quote, "company_name", None),
            "cage": getattr(submission, "planned_vendor_cage", None) or getattr(planned_quote, "cage", None),
            "unit_price": float(planned_quote.unit_price) if planned_quote and planned_quote.unit_price is not None else None,
        },
        "submission_outcome": {
            "status": getattr(submission, "status", None),
            "awarded_at": submission.awarded_at.isoformat() if submission and submission.awarded_at else None,
            "award_amount": float(submission.award_amount) if submission and submission.award_amount is not None else None,
            "winning_vendor_name": getattr(submission, "winning_vendor_name", None),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
    artifact = create_artifact(
        db,
        opp.id,
        "EXECUTION_PLAN",
        f"Execution Plan - {opp.solicitation_number or opp.id}",
        content_json=execution_plan,
    )
    return {"output": execution_plan, "artifact": _artifact_payload(artifact)}


def run_workspace_agent(agent_key: str, opp: Opportunity, db: Session, *, user_id: int | None = None) -> dict[str, Any]:
    key = _safe_text(agent_key).lower()
    if key == "opportunity_analyst":
        return _run_opportunity_analyst(db, opp, user_id=user_id)
    if key == "compliance_document":
        return _run_compliance_document_agent(db, opp, user_id=user_id)
    if key == "vendor_research":
        return _run_vendor_research_agent(db, opp)
    if key == "email_outreach":
        return _run_email_outreach_agent(db, opp, user_id=user_id)
    if key == "proposal_workspace":
        return _run_proposal_workspace_agent(db, opp)
    raise ValueError(f"Unsupported workspace agent: {agent_key}")


def workspace_agent_type(agent_key: str) -> AgentType:
    key = _safe_text(agent_key).lower()
    if key in {"opportunity_analyst", "compliance_document"}:
        return AgentType.OPPORTUNITY_ANALYZER
    if key in {"vendor_research", "email_outreach"}:
        return AgentType.VENDOR_DISCOVERY
    if key == "proposal_workspace":
        return AgentType.PROPOSAL
    raise ValueError(f"Unsupported workspace agent: {agent_key}")
