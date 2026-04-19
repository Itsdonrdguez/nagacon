from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.services.document_parser import parse_opportunity_file
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
    if "REQUEST FOR QUOTATIONS" in upper or "SOLICITATION" in upper or "STANDARD FORM 18" in upper:
        return "SOLICITATION"
    return "ATTACHMENT"


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
        parsed = parse_opportunity_file(file_record.file_path)
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
    return {
        "phase": "document_pipeline",
        "agent_key": "compliance_document",
        "source_basis": "document_processing_pipeline",
        "document_count": len(files),
        "document_insights": document_insights,
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
