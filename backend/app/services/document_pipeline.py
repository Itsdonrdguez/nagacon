from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.services.document_parser import parse_opportunity_file
from app.services.storage import local_temp_path
from app.services.workspace_service import (
    create_artifact,
    ensure_parsed,
    generate_quote_email,
    generate_submission_package,
    get_best_processed_document,
)


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _humanize_phrase(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    if re.fullmatch(r"[A-Z0-9 ,./()&-]+", text) and re.search(r"[A-Z]", text):
        text = text.title()
    return text


def _humanize_quantity(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    try:
        numeric = float(text)
        if numeric.is_integer():
            return str(int(numeric))
    except Exception:
        pass
    return text


def _humanize_date_text(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text).strip()
    for pattern in ("%Y %b %d", "%Y %B %d", "%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(normalized.title(), pattern)
            return parsed.strftime("%b %d, %Y")
        except Exception:
            continue
    return normalized.title()


def _build_document_summary_text(fields: dict[str, Any]) -> str:
    item = _humanize_phrase(fields.get("nomenclature")) or "the requested item"
    quantity = _humanize_quantity(fields.get("quantity"))
    unit = _safe_text(fields.get("unit_of_issue"))
    nsn = _safe_text(fields.get("nsn"))
    due = _humanize_date_text(fields.get("return_by"))
    delivery_days = _safe_text(fields.get("delivery_days"))
    set_aside = _safe_text(fields.get("set_aside_hint"))

    quantity_text = " ".join(part for part in [quantity, unit] if part).strip()
    if quantity_text:
        first_sentence = f"This solicitation requests quotes for {quantity_text} of {item}"
    else:
        first_sentence = f"This solicitation requests quotes for {item}"
    if nsn:
        first_sentence += f" (NSN {nsn})"
    first_sentence += "."

    detail_parts: list[str] = []
    if due:
        detail_parts.append(f"responses are due by {due}")
    if delivery_days:
        detail_parts.append(f"delivery is requested within {delivery_days} days ADO")
    if set_aside:
        detail_parts.append(f"the set-aside status is {set_aside}")

    if detail_parts:
        detail_sentence = "; ".join(detail_parts)
        detail_sentence = detail_sentence[:1].upper() + detail_sentence[1:]
        return f"{first_sentence} {detail_sentence}."
    return first_sentence


def _classify_document(file_record: OpportunityFile, text: str) -> str:
    upper = _safe_text(text).upper()
    filename = _safe_text(file_record.filename).upper()
    file_type = _safe_text(file_record.file_type).upper()
    header = upper[:2000]

    if (
        "AMENDMENT OF SOLICITATION" in header
        or "AMENDMENT NO" in header
        or "SF30" in header
        or "AMEND" in filename
    ):
        return "AMENDMENT"
    if "STATEMENT OF WORK" in upper or "PERFORMANCE WORK STATEMENT" in upper or "PWS" in upper:
        return "STATEMENT_OF_WORK"
    if "QUESTION" in upper and "ANSWER" in upper:
        return "Q_AND_A"
    if "QUOTE" in upper and "REQUEST FOR QUOTATIONS" not in upper:
        return "VENDOR_QUOTE"
    if file_type == "PDF_FALLBACK_SNAPSHOT":
        return "SOLICITATION_SNAPSHOT"
    if file_type == "SAM_NOTICE":
        return "SOLICITATION"
    if "REQUEST FOR QUOTATIONS" in upper or "SOLICITATION" in upper or "STANDARD FORM 18" in upper:
        return "SOLICITATION"
    return "ATTACHMENT"


def _extract_sam_amendment_number(text: str, filename: str | None = None) -> str | None:
    normalized = _safe_text(text)
    filename_text = _safe_text(filename)
    return (
        _first_regex_group(
            [
                r"\bAMENDMENT\s+NO\.?\s*([A-Z0-9-]{1,20})\b",
                r"\bAMEND(?:MENT)?\s*#?\s*([A-Z0-9-]{1,20})\b",
                r"\bMOD(?:IFICATION)?\s+NO\.?\s*([A-Z0-9-]{1,20})\b",
            ],
            normalized,
            flags=re.IGNORECASE,
        )
        or _first_regex_group(
            [
                r"\bAMEND(?:MENT)?[_ -]?([0-9]{1,4})\b",
                r"\bMOD[_ -]?([0-9]{1,4})\b",
            ],
            filename_text,
            flags=re.IGNORECASE,
        )
    )


def _extract_sam_period_of_performance(text: str) -> str | None:
    normalized = _safe_text(text)
    patterns = [
        r"\bPERIOD OF PERFORMANCE\b[:\s-]*(.{0,160})",
        r"\bPOP\b[:\s-]*(.{0,160})",
        r"\bPERFORMANCE PERIOD\b[:\s-]*(.{0,160})",
        r"\bBASE PERIOD\b[:\s-]*(.{0,160})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        value = re.split(r"[\r\n]", match.group(1), maxsplit=1)[0].strip(" :-")
        if value:
            return value[:160]
    return None


def _extract_sam_page_limits(text: str) -> list[str]:
    normalized = _safe_text(text)
    limits: list[str] = []
    patterns = [
        r"([A-Z][A-Za-z /-]{3,40}\s+shall\s+not\s+exceed\s+\d+\s+pages?)",
        r"(\d+\s+pages?\s+maximum\s+for\s+[A-Z][A-Za-z /-]{3,40})",
        r"([A-Z][A-Za-z /-]{3,40}\s+is\s+limited\s+to\s+\d+\s+pages?)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            value = _humanize_phrase(match.group(1))
            if value:
                limits.append(value)
    return list(dict.fromkeys(limits))[:8]


def _extract_sam_evaluation_factors(text: str) -> list[str]:
    upper = _safe_text(text).upper()
    factor_map = [
        ("TECHNICAL APPROACH", ["TECHNICAL APPROACH", "TECHNICAL PROPOSAL"]),
        ("PAST PERFORMANCE", ["PAST PERFORMANCE"]),
        ("PRICE", ["PRICE", "PRICE/COST", "COST/PRICE"]),
        ("KEY PERSONNEL", ["KEY PERSONNEL"]),
        ("STAFFING PLAN", ["STAFFING PLAN"]),
        ("MANAGEMENT APPROACH", ["MANAGEMENT APPROACH", "MANAGEMENT PLAN"]),
        ("TRANSITION PLAN", ["TRANSITION PLAN"]),
        ("QUALITY CONTROL", ["QUALITY CONTROL", "QUALITY ASSURANCE"]),
        ("CORPORATE EXPERIENCE", ["CORPORATE EXPERIENCE", "RELEVANT EXPERIENCE"]),
        ("SMALL BUSINESS PARTICIPATION", ["SMALL BUSINESS PARTICIPATION"]),
    ]
    found: list[str] = []
    for label, needles in factor_map:
        if any(needle in upper for needle in needles):
            found.append(label)
    return found


def _extract_sam_required_attachments(text: str) -> list[str]:
    upper = _safe_text(text).upper()
    items: list[str] = []
    checks = [
        ("Technical proposal volume required.", ["TECHNICAL PROPOSAL", "TECHNICAL VOLUME"]),
        ("Pricing proposal or price volume required.", ["PRICE VOLUME", "PRICING VOLUME", "COST PROPOSAL", "PRICE PROPOSAL"]),
        ("Past performance volume or references required.", ["PAST PERFORMANCE", "REFERENCE PROJECTS", "PAST PERFORMANCE QUESTIONNAIRE"]),
        ("Key personnel resumes required.", ["RESUME", "KEY PERSONNEL"]),
        ("Staffing plan required.", ["STAFFING PLAN"]),
        ("Transition plan required.", ["TRANSITION PLAN"]),
        ("Capability statement or corporate experience write-up required.", ["CAPABILITY STATEMENT", "CORPORATE EXPERIENCE"]),
    ]
    for label, needles in checks:
        if any(needle in upper for needle in needles):
            items.append(label)
    return items


def _summarize_sam_amendment_changes(text: str) -> list[str]:
    upper = _safe_text(text).upper()
    changes: list[str] = []
    if any(token in upper for token in ["DUE DATE", "CLOSING DATE", "RESPONSE DATE"]):
        changes.append("Response date or due date language appears in the amendment.")
    if any(token in upper for token in ["QUESTION", "ANSWER", "Q&A"]):
        changes.append("Question and answer content appears in the amendment package.")
    if any(token in upper for token in ["STATEMENT OF WORK", "PERFORMANCE WORK STATEMENT", "PWS", "SOW"]):
        changes.append("Scope or performance-work language may have changed.")
    if any(token in upper for token in ["ATTACHMENT", "EXHIBIT", "REVISED"]):
        changes.append("An attachment or exhibit may have been revised.")
    if any(token in upper for token in ["WAGE DETERMINATION", "SERVICE CONTRACT LABOR STANDARDS"]):
        changes.append("Labor standards or wage determination language appears in the amendment.")
    return changes


def _sam_primary_contact(raw_payload: dict[str, Any]) -> dict[str, str | None]:
    contacts = raw_payload.get("pointOfContact")
    if not isinstance(contacts, list):
        return {"name": None, "email": None, "phone": None, "summary": None}
    ranked = sorted(
        [item for item in contacts if isinstance(item, dict)],
        key=lambda item: (0 if str(item.get("type") or "").lower() == "primary" else 1, str(item.get("fullName") or "")),
    )
    if not ranked:
        return {"name": None, "email": None, "phone": None, "summary": None}
    contact = ranked[0]
    name = _safe_text(contact.get("fullName")) or None
    email = _safe_text(contact.get("email")) or None
    phone = _safe_text(contact.get("phone")) or None
    summary = " | ".join(part for part in [name, phone, email] if part) or None
    return {"name": name, "email": email, "phone": phone, "summary": summary}


def _sam_place_of_performance(raw_payload: dict[str, Any]) -> str | None:
    place = raw_payload.get("placeOfPerformance")
    if not isinstance(place, dict):
        return None
    city = ((place.get("city") or {}) if isinstance(place.get("city"), dict) else {}).get("name")
    state = ((place.get("state") or {}) if isinstance(place.get("state"), dict) else {}).get("name")
    zip_code = place.get("zip")
    country = ((place.get("country") or {}) if isinstance(place.get("country"), dict) else {}).get("name")
    parts = [str(part).strip() for part in [city, state, zip_code, country] if str(part or "").strip()]
    return ", ".join(parts) if parts else None


def _sam_source_coverage(files: list[OpportunityFile]) -> str:
    types = {str(getattr(file, "file_type", "") or "").upper() for file in files}
    if types == {"SAM_NOTICE"}:
        return "Notice only"
    if "STATEMENT_OF_WORK" in types or "AMENDMENT" in types:
        return "Notice plus supporting attachments"
    if "SAM_ATTACHMENT" in types:
        return "Notice plus attachments"
    return "Document set loaded"


def _build_sam_document_set_rollup(opp: Opportunity, files: list[OpportunityFile]) -> dict[str, Any]:
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    inventory: list[dict[str, Any]] = []
    evaluation_factors: list[str] = []
    required_attachments: list[str] = []
    page_limits: list[str] = []
    amendments: list[dict[str, Any]] = []

    precedence_docs: list[dict[str, Any]] = []
    for file in files:
        metadata = dict(getattr(file, "parsed_metadata", None) or {})
        extracted_fields = dict(metadata.get("extracted_fields") or {})
        document_type = metadata.get("document_type") or _classify_document(file, _safe_text(getattr(file, "extracted_text", None)))
        text = _safe_text(getattr(file, "extracted_text", None))
        amendment_number = _extract_sam_amendment_number(text, file.filename) if document_type == "AMENDMENT" else None
        period_of_performance = _extract_sam_period_of_performance(text)
        doc_eval_factors = _extract_sam_evaluation_factors(text)
        doc_required_attachments = _extract_sam_required_attachments(text)
        doc_page_limits = _extract_sam_page_limits(text)
        inventory.append(
            {
                "file_id": file.id,
                "filename": file.filename,
                "document_type": document_type,
                "amendment_number": amendment_number,
                "issue_date": extracted_fields.get("issue_date"),
                "return_by": extracted_fields.get("return_by"),
                "period_of_performance": period_of_performance,
                "evaluation_factor_count": len(doc_eval_factors),
                "required_attachment_count": len(doc_required_attachments),
            }
        )
        evaluation_factors.extend(doc_eval_factors)
        required_attachments.extend(doc_required_attachments)
        page_limits.extend(doc_page_limits)
        precedence_docs.append(
            {
                "file": file,
                "document_type": document_type,
                "fields": extracted_fields,
                "period_of_performance": period_of_performance,
            }
        )
        if document_type == "AMENDMENT":
            amendments.append(
                {
                    "filename": file.filename,
                    "amendment_number": amendment_number or "Amendment",
                    "issue_date": extracted_fields.get("issue_date"),
                    "return_by": extracted_fields.get("return_by"),
                    "likely_changes": _summarize_sam_amendment_changes(text),
                }
            )

    def _precedence_key(item: dict[str, Any]) -> tuple[int, float]:
        doc_type = item.get("document_type")
        priority = 4
        if doc_type == "AMENDMENT":
            priority = 0
        elif doc_type == "SOLICITATION":
            priority = 1
        elif doc_type in {"STATEMENT_OF_WORK", "ATTACHMENT"}:
            priority = 2
        created_at = getattr(item.get("file"), "created_at", None)
        created_score = created_at.timestamp() if created_at else 0.0
        return (priority, -created_score)

    precedence_docs.sort(key=_precedence_key)

    merged_fields = {
        "solicitation_number": getattr(opp, "solicitation_number", None),
        "agency": getattr(opp, "agency", None),
        "naics_code": getattr(opp, "naics_code", getattr(opp, "naics", None)),
        "set_aside_type": getattr(opp, "set_aside_type", getattr(opp, "set_aside", None)),
        "place_of_performance": getattr(opp, "place_of_performance", None) or _sam_place_of_performance(raw_payload),
        "return_by": getattr(opp, "due_at", None).isoformat() if getattr(opp, "due_at", None) else None,
        "submission_office_hint": _sam_primary_contact(raw_payload).get("summary"),
        "solicitation_contact_name": _sam_primary_contact(raw_payload).get("name"),
        "solicitation_contact_email": _sam_primary_contact(raw_payload).get("email"),
        "solicitation_contact_phone": _sam_primary_contact(raw_payload).get("phone"),
        "period_of_performance": None,
        "page_limits": [],
        "source_coverage": _sam_source_coverage(files),
    }

    merge_keys = [
        "solicitation_number",
        "return_by",
        "submission_office_hint",
        "solicitation_contact_name",
        "solicitation_contact_email",
        "solicitation_contact_phone",
        "set_aside_hint",
    ]
    for item in precedence_docs:
        fields = item.get("fields") or {}
        for key in merge_keys:
            value = fields.get(key)
            if value and not merged_fields.get(key):
                merged_fields[key] = value
        if item.get("period_of_performance") and not merged_fields.get("period_of_performance"):
            merged_fields["period_of_performance"] = item["period_of_performance"]

    merged_fields["page_limits"] = list(dict.fromkeys([item for item in page_limits if item]))[:8]

    conflict_flags: list[str] = []
    due_values = sorted({str((item.get("fields") or {}).get("return_by") or "").strip() for item in precedence_docs if (item.get("fields") or {}).get("return_by")})
    if len(due_values) > 1:
        conflict_flags.append("Documents disagree on the response due date or amendment timeline.")
    office_values = sorted({str((item.get("fields") or {}).get("submission_office_hint") or "").strip() for item in precedence_docs if (item.get("fields") or {}).get("submission_office_hint")})
    if len(office_values) > 1:
        conflict_flags.append("Documents point to different submission offices or submission channels.")
    pop_values = sorted({str(item.get("period_of_performance") or "").strip() for item in precedence_docs if item.get("period_of_performance")})
    if len(pop_values) > 1:
        conflict_flags.append("Documents appear to describe different periods of performance.")
    if len(list(dict.fromkeys([item for item in page_limits if item]))) > 1:
        conflict_flags.append("Multiple page-limit instructions were found across the document set.")

    scope_map = {
        "scope_summary": [
            f"Service acquisition for {getattr(opp, 'title', None) or 'the stated requirement'}.",
            f"Place of performance: {merged_fields.get('place_of_performance') or 'Not confirmed from the loaded notice/package yet'}.",
            f"Period of performance: {merged_fields.get('period_of_performance') or 'Not confirmed from the loaded notice/package yet'}.",
            "Performance-based work statement detected." if any(item.get("document_type") == "STATEMENT_OF_WORK" for item in inventory) else ("Only the SAM notice is loaded so far; no dedicated PWS/SOW file has been identified yet." if merged_fields.get("source_coverage") == "Notice only" else "No dedicated PWS/SOW file has been identified yet."),
        ],
        "performance_signals": [
            item for item in [
                "Technical proposal or technical volume language appears in the document set." if "TECHNICAL APPROACH" in evaluation_factors else "",
                "Past performance evidence is likely part of the evaluation." if "PAST PERFORMANCE" in evaluation_factors else "",
                "Staffing or key personnel inputs may be required." if any(factor in evaluation_factors for factor in ["KEY PERSONNEL", "STAFFING PLAN"]) else "",
                "Quality or management approach signals are present." if any(factor in evaluation_factors for factor in ["QUALITY CONTROL", "MANAGEMENT APPROACH"]) else "",
                "Only the SAM notice is loaded so far, so performance details may still be missing." if merged_fields.get("source_coverage") == "Notice only" else "",
            ] if item
        ],
    }

    return {
        "document_inventory": inventory,
        "amendment_tracker": amendments,
        "merged_fields": merged_fields,
        "conflict_flags": conflict_flags,
        "scope_map": scope_map,
        "evaluation_factors": list(dict.fromkeys([item for item in evaluation_factors if item])),
        "required_attachments": list(dict.fromkeys([item for item in required_attachments if item])),
        "service_signals": {
            "period_of_performance": merged_fields.get("period_of_performance"),
            "place_of_performance": merged_fields.get("place_of_performance"),
            "performance_work_statement_present": any(item.get("document_type") == "STATEMENT_OF_WORK" for item in inventory),
        },
    }


def _summarize_requirements(text: str) -> tuple[list[str], list[str]]:
    from app.services.agents.workspace_agents import _extract_text_requirements

    return _extract_text_requirements(text)


def _extract_fields(text: str, file_record: OpportunityFile) -> dict[str, Any]:
    from app.services.agents.workspace_agents import _extract_pdf_compliance_fields

    return _extract_pdf_compliance_fields(
        text,
        source_file=file_record.filename,
        source_file_type=file_record.file_type,
    )


def _extract_missing_information(fields: dict[str, Any], text: str) -> list[str]:
    from app.services.agents.workspace_agents import _build_pdf_missing_information

    return _build_pdf_missing_information(fields, text)


def _extract_required_actions(fields: dict[str, Any], text: str) -> list[str]:
    from app.services.agents.workspace_agents import _build_pdf_required_actions

    return _build_pdf_required_actions(fields, text)


def _extract_review_flags(fields: dict[str, Any], text: str) -> list[str]:
    from app.services.agents.workspace_agents import _build_pdf_review_flags

    return _build_pdf_review_flags(fields, text)


def _extract_vendor_request_items(fields: dict[str, Any], text: str) -> list[str]:
    from app.services.agents.workspace_agents import _build_vendor_request_items_from_pdf

    return _build_vendor_request_items_from_pdf(fields, text)


def _extract_facts(fields: dict[str, Any]) -> list[dict[str, str]]:
    from app.services.agents.workspace_agents import _build_extracted_facts_from_pdf

    return _build_extracted_facts_from_pdf(fields)


def _has_legacy_generic_requirements(items: list[str]) -> bool:
    legacy_phrases = (
        "language is present",
        "instructions are present in the solicitation",
        "referenced in the solicitation",
        "may be present in the solicitation package",
    )
    return any(any(phrase in _safe_text(item).lower() for phrase in legacy_phrases) for item in items)


def process_opportunity_file(db: Session, file_id: int, force: bool = False) -> dict[str, Any]:
    file_record = db.query(OpportunityFile).filter(OpportunityFile.id == file_id).first()
    if not file_record:
        raise ValueError("File not found")

    metadata = dict(file_record.parsed_metadata or {})
    pipeline = dict(metadata.get("_pipeline") or {})
    existing_required_actions = list(metadata.get("required_actions") or metadata.get("requirements") or [])
    if (
        not force
        and pipeline.get("status") == "completed"
        and existing_required_actions
        and not _has_legacy_generic_requirements(existing_required_actions)
        and metadata.get("review_flags") is not None
    ):
        return {
            "file_id": file_record.id,
            "status": "skipped",
            "document_type": pipeline.get("document_type"),
            "review_required": bool(pipeline.get("review_required")),
        }

    pipeline.update(
        {
            "status": "processing",
            "started_at": datetime.utcnow().isoformat(),
            "error_message": None,
            "stages": {
                "extract_agent": "running",
                "classify_agent": "pending",
                "fields_agent": "pending",
                "requirements_agent": "pending",
                "summary_agent": "pending",
            },
        }
    )
    metadata["_pipeline"] = pipeline
    file_record.parsed_metadata = metadata
    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    try:
        with local_temp_path(file_record.file_path, suffix=Path(file_record.filename or file_record.file_path).suffix) as local_path:
            parsed = parse_opportunity_file(str(local_path))
        extracted_text = _safe_text(parsed.get("text"))
        pipeline_stages = dict((file_record.parsed_metadata or {}).get("_pipeline", {}).get("stages") or {})
        pipeline_stages["extract_agent"] = "completed" if extracted_text else "failed"
        document_type = _classify_document(file_record, extracted_text)
        pipeline_stages["classify_agent"] = "completed"
        fields = _extract_fields(extracted_text, file_record) if extracted_text else {}
        pipeline_stages["fields_agent"] = "completed" if fields else "failed"
        generic_requirements, vendor_hints = _summarize_requirements(extracted_text)
        required_actions = _extract_required_actions(fields, extracted_text) if extracted_text else []
        pipeline_stages["requirements_agent"] = "completed" if (required_actions or generic_requirements or extracted_text) else "failed"
        missing_information = _extract_missing_information(fields, extracted_text) if extracted_text else [
            "No readable text was extracted from the document."
        ]
        review_flags = _extract_review_flags(fields, extracted_text) if extracted_text else [
            "The document needs review because no readable text was extracted."
        ]
        vendor_request_items = _extract_vendor_request_items(fields, extracted_text) if extracted_text else []
        if vendor_hints:
            vendor_request_items = list(dict.fromkeys(vendor_request_items + vendor_hints))
        risk_flags: list[str] = []
        if not extracted_text:
            risk_flags.append("Document text extraction did not produce usable text.")
        if not fields.get("solicitation_number"):
            risk_flags.append("Solicitation number could not be confirmed from the document.")
        if not fields.get("return_by"):
            risk_flags.append("Return-by or response date could not be confirmed from the document.")
        if review_flags:
            risk_flags.extend(review_flags)
        review_required = bool(
            not extracted_text
            or not fields.get("solicitation_number")
            or not fields.get("quantity")
            or not fields.get("return_by")
        )

        metadata = dict(file_record.parsed_metadata or {})
        metadata.update(
            {
                "parser": parsed.get("parser"),
                "document_type": document_type,
                "source_basis": "pdf_document_extraction",
                "extracted_fields": fields,
                "extracted_facts": _extract_facts(fields),
                "requirements": required_actions or generic_requirements,
                "required_actions": required_actions or generic_requirements,
                "missing_information": missing_information,
                "review_flags": review_flags,
                "vendor_request_items": vendor_request_items,
                "risk_flags": risk_flags,
                "document_summary": {
                    "title": fields.get("nomenclature"),
                    "solicitation_number": fields.get("solicitation_number"),
                    "nsn": fields.get("nsn"),
                    "quantity": fields.get("quantity"),
                    "return_by": fields.get("return_by"),
                    "set_aside_hint": fields.get("set_aside_hint"),
                    "contact_name": fields.get("solicitation_contact_name"),
                    "contact_email": fields.get("solicitation_contact_email"),
                    "contact_phone": fields.get("solicitation_contact_phone"),
                    "summary_text": _build_document_summary_text(fields),
                },
            }
        )
        metadata["_pipeline"] = {
            "status": "completed",
            "document_type": document_type,
            "review_required": review_required,
            "processed_at": datetime.utcnow().isoformat(),
            "started_at": pipeline.get("started_at"),
            "error_message": None,
            "stages": {
                **pipeline_stages,
                "summary_agent": "completed",
            },
        }
        file_record.extracted_text = extracted_text or file_record.extracted_text
        file_record.parsed_metadata = metadata
        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        return {
            "file_id": file_record.id,
            "status": "completed",
            "document_type": document_type,
            "review_required": review_required,
            "requirements_count": len(required_actions or generic_requirements),
        }
    except Exception as exc:
        metadata = dict(file_record.parsed_metadata or {})
        metadata["_pipeline"] = {
            "status": "failed",
            "document_type": None,
            "review_required": True,
            "processed_at": datetime.utcnow().isoformat(),
            "started_at": pipeline.get("started_at"),
            "error_message": str(exc),
            "stages": {
                **dict(pipeline.get("stages") or {}),
                "summary_agent": "failed",
            },
        }
        file_record.parsed_metadata = metadata
        db.add(file_record)
        db.commit()
        raise


def _build_compliance_artifact_content(db: Session, opp: Opportunity) -> dict[str, Any]:
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    best_file = get_best_processed_document(opp, files=files)
    ranked_files = ([best_file] if best_file else []) + [file for file in files if not best_file or file.id != best_file.id]
    document_insights = []
    for file in ranked_files[:5]:
        metadata = dict(getattr(file, "parsed_metadata", None) or {})
        pipeline = dict(metadata.get("_pipeline") or {})
        document_insights.append(
            {
                "file_id": file.id,
                "filename": file.filename,
                "file_type": file.file_type,
                "document_type": metadata.get("document_type"),
                "processing_status": pipeline.get("status") or ("completed" if metadata else "pending"),
                "review_required": bool(pipeline.get("review_required")),
                "has_parsed_metadata": bool(metadata),
                "has_extracted_text": bool(_safe_text(getattr(file, "extracted_text", None))),
                "parsed_keys": sorted(list(metadata.keys()))[:12],
                "text_preview": _safe_text(getattr(file, "extracted_text", None))[:500],
            }
        )

    primary_file = ranked_files[0] if ranked_files else None
    primary_metadata = dict(getattr(primary_file, "parsed_metadata", None) or {}) if primary_file else {}
    primary_text = _safe_text(getattr(primary_file, "extracted_text", None)) if primary_file else ""
    compliance_fields = dict(primary_metadata.get("extracted_fields") or {})
    if primary_file and primary_text:
        refreshed_primary_fields = _extract_fields(primary_text, primary_file)
        for key, value in refreshed_primary_fields.items():
            if value not in (None, "", []):
                compliance_fields[key] = value
    requirements = list(primary_metadata.get("required_actions") or primary_metadata.get("requirements") or [])
    if compliance_fields and primary_text:
        requirements = _extract_required_actions(compliance_fields, primary_text) or requirements
    missing_information = list(primary_metadata.get("missing_information") or [])
    if compliance_fields and primary_text:
        missing_information = _extract_missing_information(compliance_fields, primary_text)
    review_flags = list(primary_metadata.get("review_flags") or [])
    if compliance_fields and primary_text:
        review_flags = _extract_review_flags(compliance_fields, primary_text)
    vendor_request_items = list(primary_metadata.get("vendor_request_items") or [])
    if compliance_fields and primary_text:
        vendor_request_items = _extract_vendor_request_items(compliance_fields, primary_text) or vendor_request_items
    risk_flags = list(primary_metadata.get("risk_flags") or [])
    extracted_facts = list(primary_metadata.get("extracted_facts") or [])
    if compliance_fields:
        extracted_facts = _extract_facts(compliance_fields)

    for file in ranked_files[1:]:
        metadata = dict(getattr(file, "parsed_metadata", None) or {})
        risk_flags.extend(metadata.get("risk_flags") or [])

    requirements = list(dict.fromkeys([item for item in requirements if item]))
    review_flags = list(dict.fromkeys([item for item in review_flags if item]))
    vendor_request_items = list(dict.fromkeys([item for item in vendor_request_items if item]))
    risk_flags = list(dict.fromkeys([item for item in risk_flags if item]))
    missing_documents = [] if files else ["No downloaded documents are available yet."]

    parsed = ensure_parsed(db, opp)
    sam_document_set = _build_sam_document_set_rollup(opp, files) if str(getattr(opp, "source", "") or "").upper() == "SAM" else {}
    if sam_document_set.get("merged_fields"):
        for key, value in (sam_document_set.get("merged_fields") or {}).items():
            if key == "page_limits":
                continue
            if value not in (None, "", []) and not compliance_fields.get(key):
                compliance_fields[key] = value
    if compliance_fields:
        extracted_facts = _extract_facts(compliance_fields)
    if compliance_fields and primary_text:
        requirements = _extract_required_actions(compliance_fields, primary_text) or requirements
        missing_information = _extract_missing_information(compliance_fields, primary_text)
        review_flags = _extract_review_flags(compliance_fields, primary_text)
        vendor_request_items = _extract_vendor_request_items(compliance_fields, primary_text) or vendor_request_items
    evaluation_factors = sam_document_set.get("evaluation_factors") or []
    required_attachments = sam_document_set.get("required_attachments") or []
    return {
        "phase": "document_pipeline",
        "agent_key": "compliance_document",
        "source_basis": "document_processing_pipeline",
        "document_count": len(files),
        "document_insights": document_insights,
        "document_set": sam_document_set,
        "compliance_fields": compliance_fields,
        "extracted_facts": extracted_facts,
        "parsed_summary": {
            "nsn": parsed.get("nsn"),
            "nomenclature": parsed.get("nomenclature") or parsed.get("item_description"),
            "solicitations": [],
            "text_source": parsed.get("text_source") or {},
        },
        "required_actions": requirements,
        "submission_requirements": requirements,
        "evaluation_factors": evaluation_factors,
        "required_attachments": required_attachments,
        "document_findings": [
            f"{item['filename']} processed as {item.get('document_type') or item.get('file_type')}."
            for item in document_insights
        ],
        "missing_documents": missing_documents,
        "missing_information": missing_information,
        "review_flags": review_flags,
        "vendor_request_items": vendor_request_items,
        "risks": risk_flags or (["Document extraction may be incomplete for scanned or image-based PDFs."] if files else ["No files have been downloaded for compliance review yet."]),
        "generated_at": datetime.utcnow().isoformat(),
    }


def refresh_workspace_document_outputs(db: Session, opp: Opportunity) -> dict[str, Any]:
    compliance_content = _build_compliance_artifact_content(db, opp)
    compliance_artifact = create_artifact(
        db,
        opp.id,
        "COMPLIANCE_BRIEF",
        f"Compliance Brief - {opp.solicitation_number or opp.id}",
        content_json=compliance_content,
        replace_existing=True,
    )
    email_artifact = generate_quote_email(db, opp)
    submission_artifact = generate_submission_package(db, opp)
    return {
        "compliance_artifact_id": compliance_artifact.id,
        "email_artifact_id": email_artifact.id,
        "submission_package_artifact_id": submission_artifact.id,
    }


def process_opportunity_documents(db: Session, opportunity_id: int, force: bool = False) -> dict[str, Any]:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ValueError("Opportunity not found")

    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opportunity_id)
        .order_by(OpportunityFile.created_at.asc())
        .all()
    )
    processed: list[dict[str, Any]] = []
    for file in files:
        metadata = dict(file.parsed_metadata or {})
        pipeline = dict(metadata.get("_pipeline") or {})
        if force or pipeline.get("status") != "completed":
            processed.append(process_opportunity_file(db, file.id, force=force))
        else:
            processed.append(
                {
                    "file_id": file.id,
                    "status": "skipped",
                    "document_type": pipeline.get("document_type"),
                    "review_required": bool(pipeline.get("review_required")),
                }
            )

    refresh = refresh_workspace_document_outputs(db, opp) if files else {}
    return {
        "opportunity_id": opportunity_id,
        "files_processed": processed,
        "refresh": refresh,
    }
