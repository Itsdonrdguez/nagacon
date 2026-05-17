from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity, OpportunityAnalysis
from app.models.opportunity_file import OpportunityFile
from app.models.vendor import VendorQuote
from app.models.workspace import WorkspaceArtifact, WorkspaceTask
from app.repositories.company import CompanyRepository
from app.services.bid_submission_service import get_submission
from app.services.rfq_parser import get_best_opportunity_text, parse_dibbs_sources
from app.services.vendor_email_automation import _build_quote_request_body, _format_display_date
from app.services.vendor_service import sync_vendor_leads_from_parsed
from app.utils.solicitation_status import derive_solicitation_status


def _parse_nsn_from_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    u = url.lower()
    if "value=" not in u:
        return None
    try:
        q = u.split("?", 1)[1]
        for p in q.split("&"):
            if p.startswith("value="):
                return p.split("=", 1)[1].strip() or None
    except Exception:
        return None
    return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _tokenize_words(value: Any) -> set[str]:
    words = re.findall(r"[a-z0-9]{4,}", _clean_text(value).lower())
    return set(words)


def build_sam_past_performance_map(db: Session, opp: Opportunity) -> dict[str, Any]:
    if str(getattr(opp, "source", "") or "").upper() != "SAM":
        return {}

    company_repo = CompanyRepository(db)
    profile = company_repo.get_first_profile()
    if not profile:
        return {"matches": [], "summary": "No company profile is available yet.", "coverage_gaps": []}

    rows = company_repo.list_past_performance(profile.id)
    if not rows:
        return {"matches": [], "summary": "No past performance records are saved yet.", "coverage_gaps": ["Add prior project records to compare against SAM service opportunities."]}

    opp_text = " ".join(
        item for item in [
            getattr(opp, "title", None),
            getattr(opp, "description", None),
            getattr(opp, "agency", None),
            getattr(opp, "place_of_performance", None),
        ] if item
    )
    opp_tokens = _tokenize_words(opp_text)
    opp_naics = _clean_text(getattr(opp, "naics_code", getattr(opp, "naics", None)))
    opp_place = _clean_text(getattr(opp, "place_of_performance", None)).lower()

    matches: list[dict[str, Any]] = []
    for row in rows:
        score = 0
        reasons: list[str] = []
        row_naics = _clean_text(getattr(row, "naics_code", None))
        if opp_naics and row_naics and opp_naics == row_naics:
            score += 50
            reasons.append(f"NAICS match ({opp_naics})")

        row_text = " ".join(
            item for item in [
                getattr(row, "project_title", None),
                getattr(row, "description", None),
                " ".join(getattr(row, "relevance_tags", None) or []),
                getattr(row, "client_name", None),
            ] if item
        )
        row_tokens = _tokenize_words(row_text)
        overlap = sorted(list(opp_tokens & row_tokens))[:8]
        if overlap:
            score += min(len(overlap) * 6, 30)
            reasons.append(f"Scope overlap: {', '.join(overlap[:4])}")

        if opp_place:
            row_place_tokens = _tokenize_words(row_text)
            opp_place_tokens = _tokenize_words(opp_place)
            if opp_place_tokens & row_place_tokens:
                score += 10
                reasons.append("Place-of-performance language overlaps")

        if getattr(row, "project_value", None):
            reasons.append(f"Project value {getattr(row, 'project_value')}")

        matches.append(
            {
                "id": getattr(row, "id", None),
                "client_name": getattr(row, "client_name", None),
                "project_title": getattr(row, "project_title", None),
                "project_value": getattr(row, "project_value", None),
                "naics_code": row_naics or None,
                "description": getattr(row, "description", None),
                "relevance_tags": getattr(row, "relevance_tags", None) or [],
                "score": score,
                "reasons": reasons,
            }
        )

    matches.sort(key=lambda item: (item.get("score") or 0, item.get("project_value") or 0), reverse=True)
    top_matches = [item for item in matches if (item.get("score") or 0) > 0][:5]

    coverage_gaps: list[str] = []
    if not any("NAICS match" in " ".join(item.get("reasons") or []) for item in top_matches):
        coverage_gaps.append("No saved past performance record shares this opportunity's NAICS code yet.")
    if not top_matches:
        coverage_gaps.append("No strong scope overlap was found in the saved past performance records.")

    summary = (
        f"{len(top_matches)} relevant past performance record{'s' if len(top_matches) != 1 else ''} matched this opportunity."
        if top_matches else
        "No strong past performance match was identified from the saved records."
    )
    return {
        "summary": summary,
        "matches": top_matches,
        "coverage_gaps": coverage_gaps,
    }


def extract_solicitation_poc(text: str | None) -> dict[str, Any]:
    content = str(text or "").strip()
    if not content:
        return {"email": None, "phone": None, "contact_name": None, "submission_office": None}

    email_matches = re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', content)
    phone_matches = re.findall(r'(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})', content)
    office_match = re.search(r'(?:ISSUED BY|ISSUING OFFICE|CONTACT INFORMATION|POINT OF CONTACT)([\s\S]{0,400})', content, re.IGNORECASE)
    office_block = office_match.group(1).strip() if office_match else ""
    office_lines = [line.strip(" :\t") for line in office_block.splitlines() if line.strip()] if office_block else []
    contact_name = None
    submission_office = None
    if office_lines:
        submission_office = " | ".join(office_lines[:3])
        for line in office_lines[:4]:
            if not re.search(r'@|\d{3}|\bFAX\b|\bPHONE\b', line, re.IGNORECASE) and len(line.split()) <= 6:
                contact_name = line
                break

    return {
        "email": email_matches[0] if email_matches else None,
        "phone": phone_matches[0] if phone_matches else None,
        "contact_name": contact_name,
        "submission_office": submission_office,
    }


def parse_dibbs_raw_text(raw_text: str) -> dict[str, Any]:
    return parse_dibbs_sources(raw_text)


def ensure_parsed(db: Session, opp: Opportunity) -> dict[str, Any]:
    raw_payload = getattr(opp, "raw_payload", None) or {}
    dibbs_detail = raw_payload.get("dibbs_detail") or {}
    if isinstance(dibbs_detail, dict):
        structured = dibbs_detail.get("structured") if isinstance(dibbs_detail.get("structured"), dict) else dibbs_detail
        if structured and (
            structured.get("approved_sources")
            or structured.get("solicitations")
            or structured.get("nomenclature")
        ):
            parsed = dict(structured)
            parsed["text_source"] = {
                "kind": "dibbs_detail",
                "file_type": None,
                "file_id": None,
                "filename": None,
            }
            opp.parsed_json = parsed  # type: ignore[attr-defined]
            db.commit()
            return parsed

    best = get_best_opportunity_text(db, opp)
    text = (best.get("text") or "").strip()

    if not text and getattr(opp, "parsed_json", None):
        return opp.parsed_json  # type: ignore[attr-defined]

    if not text:
        parsed = {}
    else:
        parsed = parse_dibbs_sources(text, opp.url)
        parsed["text_source"] = {
            "kind": best.get("source_kind"),
            "file_type": best.get("source_file_type"),
            "file_id": best.get("source_file_id"),
            "filename": best.get("source_filename"),
        }

    if not parsed.get("nsn"):
        nsn = _parse_nsn_from_url(opp.url)
        if nsn:
            parsed["nsn"] = nsn

    opp.parsed_json = parsed  # type: ignore[attr-defined]
    db.commit()
    return parsed


def create_artifact(
    db: Session,
    opp_id: int,
    artifact_type: str,
    title: str,
    content_json: dict[str, Any] | None = None,
    file_path: str | None = None,
    replace_existing: bool = False,
) -> WorkspaceArtifact:
    content_json = dict(content_json or {})
    content_json.setdefault("_meta", {})
    content_json["_meta"].setdefault("artifact_type", artifact_type)
    content_json["_meta"].setdefault("artifact_category", {
        "CHECKLIST": "PLANNING",
        "EMAIL_DRAFT": "OUTREACH",
        "VENDOR_LIST": "RESEARCH",
        "RESEARCH_BRIEF": "RESEARCH",
        "WBPARTS_REFERENCE": "RESEARCH",
        "SUBMISSION_PACKAGE": "SUBMISSION",
    }.get(artifact_type.upper(), "GENERAL"))
    content_json["_meta"].setdefault("artifact_status", "ACTIVE")
    content_json.setdefault("_history", [])
    content_json.setdefault("_outreach_log", [])
    content_json["_meta"].setdefault("created_at", datetime.utcnow().isoformat())
    skip_history = artifact_type.upper() in {"WORKSPACE_SUMMARY_SNAPSHOT", "WBPARTS_REFERENCE"}

    if replace_existing:
        existing = (
            db.query(WorkspaceArtifact)
            .filter(
                WorkspaceArtifact.opportunity_id == opp_id,
                WorkspaceArtifact.artifact_type == artifact_type,
            )
            .order_by(WorkspaceArtifact.created_at.desc())
            .first()
        )
        if existing:
            if not skip_history:
                current_content = dict(existing.content_json or {})
                history = list(content_json.get("_history") or current_content.get("_history") or [])
                history.append(
                    {
                        "title": existing.title,
                        "content_json": {k: v for k, v in current_content.items() if k != "_history"},
                        "timestamp": datetime.utcnow().isoformat(),
                        "action": "auto_refresh" if artifact_type in {"COMPLIANCE_BRIEF", "EMAIL_DRAFT"} else "updated",
                    }
                )
                content_json["_history"] = history[-20:]
            else:
                content_json["_history"] = []
                content_json["_outreach_log"] = []
            existing.title = title
            existing.content_json = content_json
            existing.file_path = file_path
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return existing

    rec = WorkspaceArtifact(
        organization_id=getattr(db.query(Opportunity).filter(Opportunity.id == opp_id).first(), "organization_id", None),
        opportunity_id=opp_id,
        artifact_type=artifact_type,
        title=title,
        content_json=content_json,
        file_path=file_path,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def build_research_profile(opp: Opportunity, parsed: dict[str, Any] | None = None) -> dict[str, Any]:
    parsed = parsed or {}
    approved_sources = parsed.get("approved_sources") or []
    cage_codes = [x for x in (parsed.get("cage_codes") or []) if x]
    part_numbers = [x for x in (parsed.get("part_numbers") or []) if x]
    manufacturers = [x for x in (parsed.get("manufacturers") or []) if x]
    solicitation_rows = parsed.get("solicitations") or []
    due_at = opp.due_at.isoformat() if opp.due_at else None

    keyword_terms: list[str] = []
    for candidate in [
        parsed.get("nsn"),
        parsed.get("nomenclature"),
        parsed.get("item_description"),
        getattr(opp, "fsc", None),
        getattr(opp, "naics", None),
        *part_numbers[:4],
        *manufacturers[:4],
    ]:
        value = str(candidate).strip() if candidate else ""
        if not value or value.lower() in {x.lower() for x in keyword_terms}:
            continue
        keyword_terms.append(value)

    recommended_actions = [
        "Validate the item description and NSN against the source documents.",
        "Prioritize approved sources and manufacturer-linked vendors for outreach.",
        "Use USAspending award history to separate product-like incumbents from service noise.",
    ]
    if not approved_sources:
        recommended_actions.append("Run parse and vendor discovery to identify approved sources or stronger supplier evidence.")
    if due_at and derive_solicitation_status(opp.due_at) != "CLOSED":
        recommended_actions.append("Draft outreach and collect pricing inputs before the due date.")

    return {
        "solicitation_number": opp.solicitation_number,
        "title": getattr(opp, "display_title", None) or opp.title,
        "source": opp.source,
        "agency": opp.agency,
        "due_at": due_at,
        "solicitation_status": derive_solicitation_status(opp.due_at),
        "nsn": parsed.get("nsn"),
        "nomenclature": parsed.get("nomenclature") or parsed.get("item_description"),
        "naics_code": getattr(opp, "naics", None),
        "fsc_code": getattr(opp, "fsc", None),
        "keyword_terms": keyword_terms,
        "approved_source_count": len(approved_sources),
        "approved_source_names": [x.get("company_name") for x in approved_sources if x.get("company_name")][:8],
        "cage_codes": cage_codes[:10],
        "part_numbers": part_numbers[:10],
        "manufacturers": manufacturers[:10],
        "solicitation_rows": solicitation_rows[:5],
        "text_source": parsed.get("text_source") or {},
        "recommended_actions": recommended_actions,
    }


def get_best_processed_document(opp: Opportunity, files: list[OpportunityFile] | None = None) -> OpportunityFile | None:
    candidates = files or list(getattr(opp, "files", []) or [])
    if not candidates:
        return None

    def _document_rank(file: OpportunityFile) -> tuple[int, int, int, int, float]:
        metadata = dict(getattr(file, "parsed_metadata", None) or {})
        pipeline = dict(metadata.get("_pipeline") or {})
        fields = dict(metadata.get("extracted_fields") or {})
        completeness = sum(1 for key in ["solicitation_number", "nsn", "nomenclature", "quantity", "return_by", "pr_number"] if fields.get(key))
        review_penalty = 1 if pipeline.get("review_required") else 0
        snapshot_penalty = 1 if str(getattr(file, "file_type", "") or "").upper() == "PDF_FALLBACK_SNAPSHOT" else 0
        text_penalty = 0 if _safe_bool_text(getattr(file, "extracted_text", None)) else 1
        created_at = -(getattr(file, "created_at", None).timestamp() if getattr(file, "created_at", None) else 0)
        return (review_penalty, snapshot_penalty, text_penalty, -completeness, created_at)

    ranked = sorted(
        candidates,
        key=_document_rank,
    )
    return ranked[0] if ranked else None


def _safe_bool_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def get_best_processed_document_data(opp: Opportunity, files: list[OpportunityFile] | None = None) -> dict[str, Any]:
    best_file = get_best_processed_document(opp, files=files)
    if not best_file:
        return {}
    metadata = dict(getattr(best_file, "parsed_metadata", None) or {})
    summary = dict(metadata.get("document_summary") or {})
    fields = dict(metadata.get("extracted_fields") or {})
    if fields:
        summary.setdefault("title", fields.get("nomenclature"))
        summary.setdefault("solicitation_number", fields.get("solicitation_number"))
        summary.setdefault("nsn", fields.get("nsn"))
        summary.setdefault("quantity", fields.get("quantity"))
        summary.setdefault("return_by", fields.get("return_by"))
        summary.setdefault("set_aside_hint", fields.get("set_aside_hint"))
        summary.setdefault("contact_name", fields.get("solicitation_contact_name"))
        summary.setdefault("contact_email", fields.get("solicitation_contact_email"))
        summary.setdefault("contact_phone", fields.get("solicitation_contact_phone"))
        if not summary.get("summary_text"):
            try:
                from app.services.document_pipeline import _build_document_summary_text

                summary["summary_text"] = _build_document_summary_text(fields)
            except Exception:
                pass
    return {
        "file_id": best_file.id,
        "filename": best_file.filename,
        "file_type": best_file.file_type,
        "pipeline": dict(metadata.get("_pipeline") or {}),
        "summary": summary,
        "fields": fields,
        "facts": list(metadata.get("extracted_facts") or []),
        "requirements": list(metadata.get("requirements") or []),
        "missing_information": list(metadata.get("missing_information") or []),
        "vendor_request_items": list(metadata.get("vendor_request_items") or []),
        "risk_flags": list(metadata.get("risk_flags") or []),
        "text_preview": str(getattr(best_file, "extracted_text", None) or "").strip()[:800],
    }


def _first_present(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _fact(value, source: str | None = None) -> dict[str, Any]:
    return {"value": value, "source": source or None}


def _matching_solicitation_row(parsed: dict[str, Any], solicitation_number: str | None) -> dict[str, Any]:
    rows = parsed.get("solicitations") or []
    sol_key = re.sub(r"[^A-Z0-9]+", "", str(solicitation_number or "").upper())
    for row in rows:
        row_sol = re.sub(r"[^A-Z0-9]+", "", str(row.get("solicitation_number") or row.get("solicitation") or "").upper())
        if sol_key and row_sol == sol_key:
            return row
    return rows[0] if rows else {}


def fact_value(facts: dict[str, Any], key: str, fallback: Any = None) -> Any:
    value = (facts.get(key) or {}).get("value") if isinstance(facts.get(key), dict) else None
    return fallback if value in (None, "") else value


def build_normalized_facts(
    opp: Opportunity,
    parsed: dict[str, Any] | None = None,
    document_data: dict[str, Any] | None = None,
    compliance_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parsed or {}
    document_data = document_data or {}
    compliance_json = compliance_json or {}
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    document_fields = dict(document_data.get("fields") or {})
    compliance_fields = dict(compliance_json.get("compliance_fields") or {})
    document_summary = dict(document_data.get("summary") or {})
    solicitation_row = _matching_solicitation_row(parsed, getattr(opp, "solicitation_number", None))
    point_of_contact = list(raw_payload.get("pointOfContact") or [])
    primary_contact = point_of_contact[0] if point_of_contact else {}
    office_address = dict(raw_payload.get("officeAddress") or {})
    office_bits = [
        _first_present(office_address.get("city")),
        _first_present(office_address.get("state")),
        _first_present(office_address.get("zipcode")),
    ]
    submission_office_hint = " ".join(str(bit).strip() for bit in office_bits if str(bit or "").strip()) or None

    def choose(*candidates):
        for value, source in candidates:
            selected = _first_present(value)
            if selected is not None:
                return _fact(selected, source)
        return _fact(None, None)

    quantity = choose(
        (document_fields.get("quantity"), "solicitation_pdf"),
        (compliance_fields.get("quantity"), "compliance_brief"),
        (solicitation_row.get("qty"), "dibbs_detail"),
    )
    unit = choose(
        (document_fields.get("unit_of_issue"), "solicitation_pdf"),
        (compliance_fields.get("unit_of_issue"), "compliance_brief"),
    )
    return {
        "solicitation_number": choose(
            (document_fields.get("solicitation_number"), "solicitation_pdf"),
            (compliance_fields.get("solicitation_number"), "compliance_brief"),
            (solicitation_row.get("solicitation_number"), "dibbs_detail"),
            (opp.solicitation_number, "opportunity_record"),
        ),
        "nsn": choose(
            (document_fields.get("nsn"), "solicitation_pdf"),
            (compliance_fields.get("nsn"), "compliance_brief"),
            (parsed.get("nsn"), "parsed_opportunity"),
        ),
        "nomenclature": choose(
            (document_fields.get("nomenclature"), "solicitation_pdf"),
            (document_summary.get("title"), "document_summary"),
            (compliance_fields.get("nomenclature"), "compliance_brief"),
            (parsed.get("nomenclature") or parsed.get("item_description"), "parsed_opportunity"),
            (getattr(opp, "display_title", None) or opp.title, "opportunity_record"),
        ),
        "quantity": quantity,
        "unit_of_issue": unit,
        "quantity_display": _fact(
            " ".join(str(x) for x in [quantity.get("value"), unit.get("value")] if x).strip() or None,
            quantity.get("source") or unit.get("source"),
        ),
        "pr_number": choose(
            (document_fields.get("pr_number"), "solicitation_pdf"),
            (compliance_fields.get("pr_number"), "compliance_brief"),
            (solicitation_row.get("pr_number"), "dibbs_detail"),
        ),
        "return_by": choose(
            (document_fields.get("return_by"), "solicitation_pdf"),
            (compliance_fields.get("return_by"), "compliance_brief"),
            (solicitation_row.get("return_by_date"), "dibbs_detail"),
            (opp.due_at.isoformat() if getattr(opp, "due_at", None) else None, "opportunity_record"),
        ),
        "issue_date": choose(
            (document_fields.get("issue_date"), "solicitation_pdf"),
            (compliance_fields.get("issue_date"), "compliance_brief"),
            (solicitation_row.get("issue_date"), "dibbs_detail"),
            (opp.posted_at.isoformat() if getattr(opp, "posted_at", None) else None, "opportunity_record"),
        ),
        "set_aside": choose(
            (document_fields.get("set_aside_hint"), "solicitation_pdf"),
            (compliance_fields.get("set_aside_hint"), "compliance_brief"),
            (raw_payload.get("typeOfSetAsideDescription") or raw_payload.get("typeOfSetAside"), "sam_notice"),
            (getattr(opp, "set_aside", None), "opportunity_record"),
        ),
        "naics": choose((getattr(opp, "naics", None), "opportunity_record")),
        "fsc": choose(
            (document_fields.get("fsc"), "solicitation_pdf"),
            (parsed.get("fsc") or parsed.get("fsc_code"), "parsed_opportunity"),
            (getattr(opp, "fsc", None), "opportunity_record"),
        ),
        "delivery_days": choose(
            (document_fields.get("delivery_days"), "solicitation_pdf"),
            (compliance_fields.get("delivery_days"), "compliance_brief"),
        ),
        "submission_method": choose(
            (document_fields.get("submission_method"), "solicitation_pdf"),
            (compliance_fields.get("submission_method"), "compliance_brief"),
            ("Submit according to the SAM notice instructions and attachments", "sam_notice")
            if str(getattr(opp, "source", "") or "").upper() == "SAM"
            else (None, None),
        ),
        "fob_terms": choose(
            (document_fields.get("fob_terms"), "solicitation_pdf"),
            (compliance_fields.get("fob_terms"), "compliance_brief"),
        ),
        "packaging": choose(
            (document_fields.get("packaging_standard"), "solicitation_pdf"),
            (compliance_fields.get("packaging_standard"), "compliance_brief"),
        ),
        "source_file": choose(
            (document_data.get("filename"), "document_pipeline"),
            (compliance_fields.get("source_file"), "compliance_brief"),
        ),
        "poc": {
            "name": choose(
                (document_fields.get("solicitation_contact_name"), "solicitation_pdf"),
                (compliance_fields.get("solicitation_contact_name"), "compliance_brief"),
                (primary_contact.get("fullName"), "sam_notice"),
            ),
            "email": choose(
                (document_fields.get("solicitation_contact_email"), "solicitation_pdf"),
                (compliance_fields.get("solicitation_contact_email"), "compliance_brief"),
                (primary_contact.get("email"), "sam_notice"),
            ),
            "phone": choose(
                (document_fields.get("solicitation_contact_phone"), "solicitation_pdf"),
                (compliance_fields.get("solicitation_contact_phone"), "compliance_brief"),
                (primary_contact.get("phone"), "sam_notice"),
            ),
            "submission_office": choose(
                (document_fields.get("submission_office_hint"), "solicitation_pdf"),
                (compliance_fields.get("submission_office_hint"), "compliance_brief"),
                (submission_office_hint, "sam_notice"),
            ),
        },
    }


def generate_checklist(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    nsn = parsed.get("nsn")
    sol = opp.solicitation_number or ""
    due = opp.due_at.isoformat() if opp.due_at else None
    solicitation_status = derive_solicitation_status(opp.due_at)
    source = str(getattr(opp, "source", "") or "").upper()

    if source == "SAM" and solicitation_status == "CLOSED":
        items = [
            {"id": "capture_scope", "text": "Capture the final scope, NAICS, place of performance, and notice details for future pursuits.", "done": False},
            {"id": "review_docs", "text": "Review the notice package and attachments for requirements, clauses, and deliverables.", "done": False},
            {"id": "review_awards", "text": "Review award history and likely incumbents to understand how this agency buys similar work.", "done": False},
            {"id": "save_notes", "text": "Save capability, teaming, and pricing notes that can support the next similar SAM opportunity.", "done": False},
        ]
        checklist_title = f"Opportunity Research Checklist - {sol}"
        workflow_type = "sam_research"
    elif source == "SAM":
        items = [
            {"id": "confirm_notice", "text": "Confirm the notice type, due date, place of performance, and any amendment activity.", "done": False},
            {"id": "extract_requirements", "text": "Review the solicitation package and capture the core scope, deliverables, and submission requirements.", "done": False},
            {"id": "capability_match", "text": "Confirm the opportunity aligns with company capabilities, certifications, and relevant past performance.", "done": False},
            {"id": "draft_co_email", "text": "Draft outreach to the contracting officer for introduction or clarification if needed.", "done": False},
            {"id": "build_compliance_matrix", "text": "Build the compliance matrix, required attachments list, and proposal notes.", "done": False},
            {"id": "assign_tasks", "text": "Assign proposal tasks, owners, and internal deadlines before the submission date.", "done": False},
            {"id": "prepare_submission", "text": "Prepare the proposal package and final submission review before the due date.", "done": False},
        ]
        checklist_title = f"Proposal Checklist - {sol}"
        workflow_type = "sam_proposal"
    elif solicitation_status == "CLOSED":
        items = [
            {"id": "confirm_record", "text": "Confirm the closed solicitation record is mapped to the correct item and source documents.", "done": False},
            {"id": "review_docs", "text": "Review and parse the available documents for item, NSN, and requirement signals.", "done": False},
            {"id": "review_sources", "text": "Review approved sources, manufacturers, and part numbers for future opportunities.", "done": False},
            {"id": "review_awardees", "text": "Use USAspending and prior award history to identify incumbents and likely suppliers.", "done": False},
            {"id": "capture_notes", "text": "Capture pricing, vendor, and compliance notes that can help on future bids.", "done": False},
        ]
        checklist_title = f"Bid Checklist - {sol}"
        workflow_type = "dibbs_research"
    else:
        items = [
            {"id": "confirm_row", "text": "Confirm you are bidding the correct solicitation row for this NSN.", "done": False},
            {"id": "download_docs", "text": "Download/verify technical documents (if any).", "done": False},
            {"id": "approved_sources", "text": "Review approved sources list; pick supplier(s) to quote.", "done": False},
            {"id": "pricing_inputs", "text": "Collect pricing inputs (qty, shipping, lead time, payment terms).", "done": False},
            {"id": "compliance", "text": "Review solicitation requirements / DFARS-FAR clauses on page.", "done": False},
            {"id": "submit_quote", "text": "Prepare and submit quote before due date.", "done": False},
        ]
        checklist_title = f"Bid Checklist - {sol}"
        workflow_type = "dibbs_quote"

    content = {
        "nsn": nsn,
        "solicitation": sol,
        "due_at": due,
        "solicitation_status": solicitation_status,
        "workflow_type": workflow_type,
        "checklist": items,
    }
    return create_artifact(db, opp.id, "CHECKLIST", checklist_title, content_json=content)


def generate_compliance_matrix(db: Session, opp: Opportunity) -> WorkspaceArtifact | None:
    if str(getattr(opp, "source", "") or "").upper() != "SAM":
        return None

    compliance_artifact = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type == "COMPLIANCE_BRIEF",
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    compliance_json = dict(getattr(compliance_artifact, "content_json", None) or {})
    if not compliance_json:
        return None

    required_actions = list(compliance_json.get("required_actions") or compliance_json.get("submission_requirements") or [])
    review_flags = list(compliance_json.get("review_flags") or [])
    missing_information = list(compliance_json.get("missing_information") or [])
    fields = dict(compliance_json.get("compliance_fields") or {})
    due_at = getattr(opp, "due_at", None)

    matrix_rows = []
    for index, item in enumerate(required_actions):
        row_due = None
        if due_at:
            offset_days = 14 if index < 2 else 7 if index < 5 else 3
            row_due = (due_at - timedelta(days=offset_days)).isoformat()
        matrix_rows.append(
            {
                "id": f"requirement-{index + 1}",
                "category": "Requirement",
                "requirement": str(item),
                "status": "OPEN",
                "owner_hint": "Proposal Team",
                "due_at": row_due,
                "source": fields.get("source_file"),
            }
        )
    for index, item in enumerate(review_flags):
        matrix_rows.append(
            {
                "id": f"review-{index + 1}",
                "category": "Review",
                "requirement": str(item),
                "status": "OPEN",
                "owner_hint": "Capture Review",
                "due_at": (due_at - timedelta(days=5)).isoformat() if due_at else None,
                "source": fields.get("source_file"),
            }
        )
    for index, item in enumerate(missing_information):
        matrix_rows.append(
            {
                "id": f"missing-{index + 1}",
                "category": "Missing Information",
                "requirement": str(item),
                "status": "OPEN",
                "owner_hint": "Capture Review",
                "due_at": (due_at - timedelta(days=7)).isoformat() if due_at else None,
                "source": fields.get("source_file"),
            }
        )

    content = {
        "workflow_type": "sam_compliance_matrix",
        "solicitation": getattr(opp, "solicitation_number", None),
        "source_file": fields.get("source_file"),
        "summary": compliance_json.get("summary") or compliance_json.get("summary_text"),
        "matrix_rows": matrix_rows,
        "required_actions": required_actions,
        "review_flags": review_flags,
        "missing_information": missing_information,
    }
    return create_artifact(
        db,
        opp.id,
        "COMPLIANCE_MATRIX",
        f"Compliance Matrix - {getattr(opp, 'solicitation_number', None) or opp.id}",
        content_json=content,
        replace_existing=True,
    )


def seed_proposal_tasks(db: Session, opp: Opportunity) -> list[WorkspaceTask]:
    if str(getattr(opp, "source", "") or "").upper() != "SAM":
        return []

    checklist_artifact = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type == "CHECKLIST",
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    checklist_items = list((getattr(checklist_artifact, "content_json", None) or {}).get("checklist") or [])

    compliance_matrix = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type == "COMPLIANCE_MATRIX",
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    matrix_rows = list((getattr(compliance_matrix, "content_json", None) or {}).get("matrix_rows") or [])

    existing_tasks = (
        db.query(WorkspaceTask)
        .filter(WorkspaceTask.opportunity_id == opp.id)
        .order_by(WorkspaceTask.created_at.desc())
        .all()
    )
    existing_keys = {
        (str(task.task_type or "").strip().upper(), str(task.notes or "").strip().lower())
        for task in existing_tasks
    }

    created: list[WorkspaceTask] = []

    def _maybe_add(task_type: str, notes: str, due_at_text: str | None = None):
        clean_notes = str(notes or "").strip()
        if not clean_notes:
            return
        key = (task_type.strip().upper(), clean_notes.lower())
        if key in existing_keys:
            return
        due_value = None
        if due_at_text:
            try:
                due_value = datetime.fromisoformat(due_at_text)
            except Exception:
                due_value = None
        rec = WorkspaceTask(
            organization_id=getattr(opp, "organization_id", None),
            opportunity_id=opp.id,
            task_type=task_type,
            status="OPEN",
            due_at=due_value,
            notes=clean_notes,
        )
        db.add(rec)
        created.append(rec)
        existing_keys.add(key)

    due_at = getattr(opp, "due_at", None)
    if due_at:
        seed_tasks = [
            ("NOTICE_REVIEW", "Confirm the notice type, due date, place of performance, and amendment history.", (due_at - timedelta(days=10)).isoformat()),
            ("SCOPE_REVIEW", "Capture the core scope, deliverables, labor expectations, and submission requirements from the solicitation.", (due_at - timedelta(days=9)).isoformat()),
            ("PAST_PERFORMANCE", "Match the opportunity to relevant past performance, certifications, and capability statement material.", (due_at - timedelta(days=7)).isoformat()),
            ("CO_OUTREACH", "Send clarification questions or an introduction to the contracting officer if outreach is needed.", (due_at - timedelta(days=6)).isoformat()),
            ("FINAL_REVIEW", "Run a final compliance and submission review before the due date.", (due_at - timedelta(days=2)).isoformat()),
        ]
    else:
        seed_tasks = [
            ("NOTICE_REVIEW", "Confirm the notice type, due date, place of performance, and amendment history.", None),
            ("SCOPE_REVIEW", "Capture the core scope, deliverables, labor expectations, and submission requirements from the solicitation.", None),
            ("PAST_PERFORMANCE", "Match the opportunity to relevant past performance, certifications, and capability statement material.", None),
            ("CO_OUTREACH", "Send clarification questions or an introduction to the contracting officer if outreach is needed.", None),
            ("FINAL_REVIEW", "Run a final compliance and submission review before the due date.", None),
        ]

    for task_type, notes, due_at_text in seed_tasks:
        _maybe_add(task_type, notes, due_at_text)

    for row in matrix_rows:
        if not isinstance(row, dict):
            continue
        task_type = "COMPLIANCE_REVIEW" if row.get("category") in {"Review", "Missing Information"} else "COMPLIANCE_STEP"
        _maybe_add(task_type, str(row.get("requirement") or ""), row.get("due_at"))

    if created:
        db.commit()
        for rec in created:
            db.refresh(rec)
    return created


def generate_vendor_shortlist(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    sync_stats = sync_vendor_leads_from_parsed(db, opp)
    research_profile = build_research_profile(opp, parsed)
    sources = parsed.get("approved_sources") or []
    vendors = []
    for s in sources:
        vendors.append({
            "cage": s.get("cage"),
            "company_name": s.get("company_name"),
            "part_number": s.get("part_number"),
            "contact": None,
            "email": None,
            "phone": None,
            "quoted": False,
            "unit_price": None,
            "lead_time_days": None,
            "notes": None,
        })

    content = {
        "nsn": parsed.get("nsn"),
        "item_description": parsed.get("item_description") or parsed.get("nomenclature"),
        "approved_source_count": len(vendors),
        "lead_sync": sync_stats,
        "cage_codes": parsed.get("cage_codes") or [],
        "part_numbers": parsed.get("part_numbers") or [],
        "text_source": parsed.get("text_source") or {},
        "research_profile": research_profile,
        "vendors": vendors,
    }
    sol = opp.solicitation_number or ""
    return create_artifact(db, opp.id, "VENDOR_LIST", f"Vendor Shortlist - {sol}", content_json=content)


def generate_research_brief(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    document_data = get_best_processed_document_data(opp, files=files)
    try:
        from app.services.document_pipeline import _build_compliance_artifact_content

        compliance_json = _build_compliance_artifact_content(db, opp)
    except Exception:
        compliance_json = {}
    normalized_facts = build_normalized_facts(opp, parsed, document_data, compliance_json)
    research_profile = build_research_profile(opp, parsed)
    nsn_intelligence: dict[str, Any] = {}
    try:
        from app.services.intelligence.nsn_intelligence_service import get_nsn_intelligence

        nsn_intelligence = get_nsn_intelligence(db, opp)
    except Exception:
        nsn_intelligence = {}

    usaspending_snapshot: dict[str, Any] = {}
    try:
        from app.services.research.usaspending_research_service import search_usaspending_for_opportunity

        research = search_usaspending_for_opportunity(opp, db=db)
        usaspending_snapshot = {
            "awards_found": research.get("awards_found", 0),
            "likely_vendors": (research.get("likely_vendors") or [])[:5],
            "product_like_vendors": (research.get("product_like_vendors") or [])[:5],
            "query_debug": (research.get("query_debug") or [])[:5],
        }
    except Exception as exc:
        usaspending_snapshot = {
            "awards_found": 0,
            "likely_vendors": [],
            "product_like_vendors": [],
            "query_debug": [],
            "error": str(exc),
        }

    risks = []
    if not research_profile.get("nsn"):
        risks.append("NSN was not extracted from the current opportunity text.")
    if not research_profile.get("approved_source_count"):
        risks.append("No approved sources were identified in the parsed data.")
    if not usaspending_snapshot.get("likely_vendors"):
        risks.append("USAspending did not return strong likely vendors yet.")

    content = {
        "research_profile": research_profile,
        "normalized_facts": normalized_facts,
        "nsn_intelligence": nsn_intelligence,
        "usaspending_snapshot": usaspending_snapshot,
        "risks": risks,
        "summary": {
            "source": opp.source,
            "agency": opp.agency,
            "solicitation_number": fact_value(normalized_facts, "solicitation_number", opp.solicitation_number),
            "title": fact_value(normalized_facts, "nomenclature", getattr(opp, "display_title", None) or opp.title),
            "solicitation_status": research_profile.get("solicitation_status"),
        },
    }
    sol = opp.solicitation_number or str(opp.id)
    return create_artifact(db, opp.id, "RESEARCH_BRIEF", f"Research Brief - {sol}", content_json=content, replace_existing=True)


def generate_quote_email(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    document_data = get_best_processed_document_data(opp, files=files)
    normalized_facts = build_normalized_facts(opp, parsed, document_data, {})
    document_fields = dict(document_data.get("fields") or {})
    document_summary = dict(document_data.get("summary") or {})
    nsn = parsed.get("nsn") or ""
    sol = opp.solicitation_number or ""
    qty = None
    due = opp.due_at.isoformat() if opp.due_at else None
    nomenclature = parsed.get("item_description") or parsed.get("nomenclature") or getattr(opp, "display_title", None) or opp.title
    solicitations = parsed.get("solicitations") or []
    text_source = parsed.get("text_source") or {}

    sol_key = re.sub(r"[^A-Za-z0-9]+", "", sol.upper())
    solicitation_row = None
    for r in solicitations:
        if r.get("solicitation") == sol_key or r.get("solicitation_number") == sol:
            qty = r.get("qty")
            solicitation_row = r
            break

    best_processed_file = get_best_processed_document(opp, files=files)
    extracted_file = best_processed_file or next((file for file in files if getattr(file, "extracted_text", None)), None)
    extracted_preview = ""
    if extracted_file and getattr(extracted_file, "extracted_text", None):
        extracted_preview = str(extracted_file.extracted_text).strip()[:800]
    poc = extract_solicitation_poc(getattr(extracted_file, "extracted_text", None) or getattr(opp, "raw_text", None))
    poc = {
        "email": document_fields.get("solicitation_contact_email") or poc.get("email"),
        "phone": document_fields.get("solicitation_contact_phone") or poc.get("phone"),
        "contact_name": document_fields.get("solicitation_contact_name") or poc.get("contact_name"),
        "submission_office": document_fields.get("submission_office_hint") or poc.get("submission_office"),
    }

    nsn = fact_value(normalized_facts, "nsn", document_fields.get("nsn") or document_summary.get("nsn") or nsn)
    sol = fact_value(normalized_facts, "solicitation_number", document_fields.get("solicitation_number") or sol)
    qty = fact_value(normalized_facts, "quantity", document_fields.get("quantity") or qty)
    quantity_display = fact_value(normalized_facts, "quantity_display", str(qty) if qty is not None else "")
    due = fact_value(normalized_facts, "return_by", document_fields.get("return_by") or due)
    nomenclature = fact_value(normalized_facts, "nomenclature", document_fields.get("nomenclature") or document_summary.get("title") or nomenclature)
    pr_number = fact_value(normalized_facts, "pr_number", document_fields.get("pr_number") or (solicitation_row.get("pr_number") if solicitation_row else "") or "")
    poc = {
        "email": fact_value((normalized_facts.get("poc") or {}), "email", poc.get("email")),
        "phone": fact_value((normalized_facts.get("poc") or {}), "phone", poc.get("phone")),
        "contact_name": fact_value((normalized_facts.get("poc") or {}), "name", poc.get("contact_name")),
        "submission_office": fact_value((normalized_facts.get("poc") or {}), "submission_office", poc.get("submission_office")),
    }

    document_signals: list[str] = []
    if document_fields.get("return_by"):
        document_signals.append(f"Return by {document_fields.get('return_by')}")
    elif solicitation_row and solicitation_row.get("return_by_date"):
        document_signals.append(f"Return by {solicitation_row.get('return_by_date')}")
    if quantity_display:
        document_signals.append(f"Quantity {quantity_display}")
    elif solicitation_row and solicitation_row.get("qty"):
        document_signals.append(f"Quantity {solicitation_row.get('qty')}")
    if document_fields.get("pr_number"):
        document_signals.append(f"PR {document_fields.get('pr_number')}")
    elif solicitation_row and solicitation_row.get("pr_number"):
        document_signals.append(f"PR {solicitation_row.get('pr_number')}")
    if document_data.get("summary", {}).get("summary_text"):
        document_signals.append(document_data["summary"]["summary_text"])
    if solicitation_row:
        if solicitation_row.get("return_by_date"):
            document_signals.append(f"Solicitation row return by {solicitation_row.get('return_by_date')}")
    if extracted_preview:
        document_signals.append("Source document text was parsed and reviewed for this draft")
    if poc.get("email"):
        document_signals.append(f"Solicitation POC email {poc.get('email')}")
    if poc.get("phone"):
        document_signals.append(f"Solicitation POC phone {poc.get('phone')}")

    request_points = [
        "unit pricing",
        "lead time / availability",
        "shipping terms",
    ]
    if document_data.get("vendor_request_items"):
        request_points.extend(document_data.get("vendor_request_items") or [])
    elif solicitation_row and solicitation_row.get("return_by_date"):
        request_points.append("ability to support the return-by timeline")
    if poc.get("email") or poc.get("phone"):
        request_points.append("whether the quote must be copied to the solicitation point of contact or issuing office")
    request_points = list(dict.fromkeys([item for item in request_points if item]))

    contact_hint = []
    if poc.get("contact_name"):
        contact_hint.append(f"POC {poc.get('contact_name')}")
    if poc.get("email"):
        contact_hint.append(f"email {poc.get('email')}")
    if poc.get("phone"):
        contact_hint.append(f"phone {poc.get('phone')}")
    if poc.get("submission_office"):
        contact_hint.append(f"office {poc.get('submission_office')}")

    subject = f"Quote Request | {sol or nomenclature or 'Government Opportunity'}{f' | NSN {nsn}' if nsn else ''}".strip()
    body = _build_quote_request_body(
        recipient_name=None,
        solicitation=sol,
        title=getattr(opp, "display_title", None) or getattr(opp, "title", "") or nomenclature,
        agency=getattr(opp, "agency", None) or "",
        due_at=solicitation_row.get("return_by_date") if solicitation_row and solicitation_row.get("return_by_date") else (due or ""),
        nsn=nsn,
        quantity=quantity_display or (str(qty) if qty is not None else ""),
        item_name=nomenclature,
        part_number="",
        cage="",
        pr_number=pr_number,
    )
    content = {
        "subject": subject,
        "body": body,
        "normalized_facts": normalized_facts,
        "nsn": nsn,
        "item": nomenclature,
        "quantity": qty,
        "quantity_display": quantity_display,
        "due_at": due,
        "solicitation_row": solicitation_row,
        "document_context": {
            "text_source": text_source,
            "document_signals": document_signals,
            "source_file": document_data.get("filename") or getattr(extracted_file, "filename", None),
            "document_type": document_data.get("pipeline", {}).get("document_type") or document_fields.get("document_type"),
            "extracted_preview": (document_data.get("text_preview") or extracted_preview)[:500] if (document_data.get("text_preview") or extracted_preview) else "",
        },
        "solicitation_poc": poc,
        "vendor_request_items": request_points,
        "response_due_display": _format_display_date(solicitation_row.get("return_by_date") if solicitation_row and solicitation_row.get("return_by_date") else due),
    }
    return create_artifact(
        db,
        opp.id,
        "EMAIL_DRAFT",
        f"Quote Email Draft - {sol}",
        content_json=content,
        replace_existing=True,
    )


def generate_contracting_officer_email(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    document_data = get_best_processed_document_data(opp, files=files)
    normalized_facts = build_normalized_facts(opp, parsed, document_data, {})
    document_fields = dict(document_data.get("fields") or {})
    document_summary = dict(document_data.get("summary") or {})
    best_processed_file = get_best_processed_document(opp, files=files)
    extracted_file = best_processed_file or next((file for file in files if getattr(file, "extracted_text", None)), None)
    extracted_preview = ""
    if extracted_file and getattr(extracted_file, "extracted_text", None):
        extracted_preview = str(extracted_file.extracted_text).strip()[:800]

    poc = extract_solicitation_poc(getattr(extracted_file, "extracted_text", None) or getattr(opp, "raw_text", None))
    poc = {
        "email": document_fields.get("solicitation_contact_email") or poc.get("email"),
        "phone": document_fields.get("solicitation_contact_phone") or poc.get("phone"),
        "contact_name": document_fields.get("solicitation_contact_name") or poc.get("contact_name"),
        "submission_office": document_fields.get("submission_office_hint") or poc.get("submission_office"),
    }
    poc = {
        "email": fact_value((normalized_facts.get("poc") or {}), "email", poc.get("email")),
        "phone": fact_value((normalized_facts.get("poc") or {}), "phone", poc.get("phone")),
        "contact_name": fact_value((normalized_facts.get("poc") or {}), "name", poc.get("contact_name")),
        "submission_office": fact_value((normalized_facts.get("poc") or {}), "submission_office", poc.get("submission_office")),
    }

    company_profile = CompanyRepository(db).get_first_profile()
    company_name = getattr(company_profile, "legal_name", None) or "[Your Company]"
    primary_contact_name = getattr(company_profile, "primary_contact_name", None) or "[Your Name]"
    primary_contact_email = getattr(company_profile, "primary_contact_email", None) or "[Your Email]"
    primary_contact_phone = getattr(company_profile, "primary_contact_phone", None) or "[Your Phone]"
    capability_statement_url = getattr(company_profile, "capability_statement_url", None) or "[Capability Statement Link]"

    solicitation = fact_value(normalized_facts, "solicitation_number", document_fields.get("solicitation_number") or getattr(opp, "solicitation_number", None) or "")
    due_at = fact_value(normalized_facts, "return_by", document_fields.get("return_by") or (opp.due_at.isoformat() if opp.due_at else "") or "")
    title = getattr(opp, "display_title", None) or getattr(opp, "title", None) or document_summary.get("title") or "Opportunity"
    naics = fact_value(normalized_facts, "naics", document_fields.get("naics") or getattr(opp, "naics", None) or "")
    set_aside = fact_value(normalized_facts, "set_aside", document_fields.get("set_aside_hint") or getattr(opp, "set_aside", None) or "")
    place = getattr(opp, "place_of_performance", None) or ""

    subject = f"Question Regarding Solicitation {solicitation or opp.id} | {title}".strip()
    recipient_name = poc.get("contact_name") or "Contracting Officer"
    body = (
        f"Hello {recipient_name},\n\n"
        f"My name is {primary_contact_name}, and I am reaching out on behalf of {company_name} regarding solicitation {solicitation or '[SOLICITATION NUMBER]'}. \n\n"
        "We are reviewing this opportunity and would appreciate any clarification you can provide before we proceed further.\n\n"
        "Opportunity reference:\n"
        f"- Solicitation: {solicitation or 'Please confirm'}\n"
        f"- Title: {title}\n"
        f"- Agency: {getattr(opp, 'agency', None) or 'Agency unavailable'}\n"
        f"- Due Date: {_format_display_date(due_at) or due_at or 'Please confirm'}\n"
        + (f"- NAICS: {naics}\n" if naics else "")
        + (f"- Set-Aside: {set_aside}\n" if set_aside else "")
        + (f"- Place of Performance: {place}\n" if place else "")
        + "\n"
        "At this stage, we would especially appreciate guidance on:\n"
        "- Any amendments or revised attachments that should be reviewed.\n"
        "- Submission instructions or evaluation details that deserve close attention.\n"
        "- Whether a capability statement or introductory materials would be useful before submission.\n\n"
        f"Our capability statement is available here: {capability_statement_url}\n\n"
        "Thank you for your time and consideration.\n\n"
        f"Best regards,\n{primary_contact_name}\n{company_name}\n{primary_contact_phone}\n{primary_contact_email}\n"
    )

    document_signals: list[str] = []
    if due_at:
        document_signals.append(f"Due {due_at}")
    if naics:
        document_signals.append(f"NAICS {naics}")
    if set_aside:
        document_signals.append(f"Set-aside {set_aside}")
    if poc.get("email"):
        document_signals.append(f"POC email {poc.get('email')}")
    if poc.get("phone"):
        document_signals.append(f"POC phone {poc.get('phone')}")
    if extracted_preview:
        document_signals.append("Source document text was used to ground this draft")

    content = {
        "to": poc.get("email"),
        "subject": subject,
        "body": body,
        "contact_name": poc.get("contact_name"),
        "contact_phone": poc.get("phone"),
        "submission_office": poc.get("submission_office"),
        "message_type": "contracting_officer",
        "company_context": {
            "company_name": company_name,
            "primary_contact_name": primary_contact_name,
            "primary_contact_email": primary_contact_email,
            "primary_contact_phone": primary_contact_phone,
            "capability_statement_url": capability_statement_url,
        },
        "document_context": {
            "source_file": document_data.get("filename") or getattr(extracted_file, "filename", None),
            "document_type": document_data.get("pipeline", {}).get("document_type") or document_fields.get("document_type"),
            "document_signals": document_signals,
            "extracted_preview": (document_data.get("text_preview") or extracted_preview)[:500] if (document_data.get("text_preview") or extracted_preview) else "",
        },
        "solicitation_poc": poc,
    }
    return create_artifact(
        db,
        opp.id,
        "CO_EMAIL_DRAFT",
        f"Contracting Officer Email Draft - {solicitation or opp.id}",
        content_json=content,
        replace_existing=True,
    )


def generate_submission_package(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    submission = get_submission(db, opp.id)
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc())
        .all()
    )
    quotes = (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opp.id)
        .order_by(VendorQuote.updated_at.desc())
        .all()
    )

    analysis_artifact = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type == "OPPORTUNITY_ANALYSIS",
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    email_artifact = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type.in_(["EMAIL_DRAFT", "OUTREACH_PLAN"]),
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )

    from app.services.document_pipeline import _build_compliance_artifact_content
    from app.services.pricing_intelligence import summarize_price_history
    from app.services.recommendation_engine import build_workspace_recommendation
    from app.services.solicitation_memory import build_solicitation_memory

    compliance_json = _build_compliance_artifact_content(db, opp)
    solicitation_memory = build_solicitation_memory(db, opp)
    recommendation_json = build_workspace_recommendation(
        db,
        opp,
        parsed=parsed,
        files=files,
        quotes=quotes,
        submission=submission,
        solicitation_memory=solicitation_memory,
    )
    analysis_json = dict(getattr(analysis_artifact, "content_json", None) or {})
    email_json = dict(getattr(email_artifact, "content_json", None) or {})
    compliance_fields = dict(compliance_json.get("compliance_fields") or {})
    document_data = get_best_processed_document_data(opp, files=files)
    normalized_facts = build_normalized_facts(opp, parsed, document_data, compliance_json)
    missing_information = list(compliance_json.get("missing_information") or [])
    review_flags = list(compliance_json.get("review_flags") or [])
    vendor_request_items = list(email_json.get("vendor_request_items") or compliance_json.get("vendor_request_items") or [])
    price_history = summarize_price_history(db, opp.id)
    nsn_intelligence: dict[str, Any] = {}
    research_brief = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type == "RESEARCH_BRIEF",
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    if research_brief and isinstance(research_brief.content_json, dict):
        nsn_intelligence = dict(research_brief.content_json.get("nsn_intelligence") or {})

    planned_quote = None
    if submission and submission.planned_vendor_quote_id:
        planned_quote = next((quote for quote in quotes if quote.id == submission.planned_vendor_quote_id), None)
    if not planned_quote and submission and submission.planned_vendor_cage:
        planned_quote = next((quote for quote in quotes if quote.cage == submission.planned_vendor_cage), None)
    if not planned_quote and quotes:
        planned_quote = quotes[0]

    quote_snapshot = [
        {
            "id": quote.id,
            "company_name": quote.company_name,
            "cage": quote.cage,
            "status": quote.status,
            "unit_price": float(quote.unit_price) if quote.unit_price is not None else None,
            "lead_time_days": quote.lead_time_days,
            "email": quote.email,
            "notes": quote.notes,
        }
        for quote in quotes[:10]
    ]

    content = {
        "summary": {
            "title": fact_value(normalized_facts, "nomenclature", getattr(opp, "display_title", None) or opp.title),
            "solicitation_number": fact_value(normalized_facts, "solicitation_number", opp.solicitation_number),
            "source": opp.source,
            "agency": opp.agency,
            "due_at": fact_value(normalized_facts, "return_by", opp.due_at.isoformat() if opp.due_at else None),
            "solicitation_status": derive_solicitation_status(opp.due_at),
            "nsn": fact_value(normalized_facts, "nsn", parsed.get("nsn")),
            "nomenclature": fact_value(normalized_facts, "nomenclature", parsed.get("nomenclature") or parsed.get("item_description")),
            "quantity": fact_value(normalized_facts, "quantity", None),
            "quantity_display": fact_value(normalized_facts, "quantity_display", None),
            "pr_number": fact_value(normalized_facts, "pr_number", None),
        },
        "planned_vendor": {
            "quote_id": getattr(submission, "planned_vendor_quote_id", None),
            "company_name": getattr(submission, "planned_vendor_name", None) or getattr(planned_quote, "company_name", None),
            "cage": getattr(submission, "planned_vendor_cage", None) or getattr(planned_quote, "cage", None),
            "unit_price": float(planned_quote.unit_price) if planned_quote and planned_quote.unit_price is not None else None,
            "lead_time_days": getattr(planned_quote, "lead_time_days", None),
            "email": getattr(planned_quote, "email", None),
        },
        "submission": {
            "status": getattr(submission, "status", "DRAFT"),
            "submitted_at": submission.submitted_at.isoformat() if submission and submission.submitted_at else None,
            "submitted_unit_price": float(submission.submitted_unit_price) if submission and submission.submitted_unit_price is not None else None,
            "submitted_vendor_name": getattr(submission, "submitted_vendor_name", None),
            "submitted_vendor_cage": getattr(submission, "submitted_vendor_cage", None),
            "awarded_at": submission.awarded_at.isoformat() if submission and submission.awarded_at else None,
            "award_amount": float(submission.award_amount) if submission and submission.award_amount is not None else None,
            "winning_vendor_name": getattr(submission, "winning_vendor_name", None),
            "winning_vendor_cage": getattr(submission, "winning_vendor_cage", None),
            "outcome_summary": getattr(submission, "outcome_summary", None),
            "notes": getattr(submission, "notes", None),
        },
        "compliance": {
            "fields": compliance_fields,
            "normalized_facts": normalized_facts,
            "missing_information": missing_information,
            "requirements": list(compliance_json.get("required_actions") or compliance_json.get("submission_requirements") or []),
            "clauses_or_requirements": list(compliance_fields.get("clauses_or_requirements") or []),
            "review_flags": review_flags,
        },
        "vendor_request_items": vendor_request_items,
        "documents": sorted(
            [
                {
                    "id": file.id,
                    "filename": file.filename,
                    "file_type": file.file_type,
                    "created_at": file.created_at.isoformat() if file.created_at else None,
                }
                for file in files[:15]
            ],
            key=lambda item: (
                1 if str(item.get("file_type") or "").upper() == "PDF_FALLBACK_SNAPSHOT" else 0,
                -(datetime.fromisoformat(item["created_at"]).timestamp() if item.get("created_at") else 0),
            ),
        ),
        "quotes": quote_snapshot,
        "price_history": price_history,
        "nsn_intelligence": nsn_intelligence,
        "analysis": {
            "executive_assessment": analysis_json.get("executive_assessment") or recommendation_json.get("summary"),
            "bid_posture": analysis_json.get("bid_posture") or recommendation_json.get("bid_posture"),
            "recommended_next_actions": list(analysis_json.get("recommended_next_actions") or recommendation_json.get("next_actions") or []),
            "recommendation": recommendation_json,
        },
        "generated_at": datetime.utcnow().isoformat(),
    }
    sol = opp.solicitation_number or str(opp.id)
    return create_artifact(db, opp.id, "SUBMISSION_PACKAGE", f"Submission Package - {sol}", content_json=content, replace_existing=True)


def export_workspace_zip_bytes(db: Session, opp: Opportunity) -> bytes:
    parsed = ensure_parsed(db, opp)
    analysis = db.query(OpportunityAnalysis).filter(OpportunityAnalysis.opportunity_id == opp.id).first()
    artifacts = (
        db.query(WorkspaceArtifact)
        .filter(WorkspaceArtifact.opportunity_id == opp.id)
        .order_by(WorkspaceArtifact.created_at.desc())
        .all()
    )
    tasks = (
        db.query(WorkspaceTask)
        .filter(WorkspaceTask.opportunity_id == opp.id)
        .order_by(WorkspaceTask.created_at.desc())
        .all()
    )

    payload_opp = {
        "id": opp.id,
        "source": opp.source,
        "solicitation_number": opp.solicitation_number,
        "title": opp.title,
        "fsc": opp.fsc,
        "posted_at": opp.posted_at.isoformat() if opp.posted_at else None,
        "due_at": opp.due_at.isoformat() if opp.due_at else None,
        "url": opp.url,
        "decision_status": getattr(opp, "decision_status", None),
        "decision_note": getattr(opp, "decision_note", None),
        "decision_updated_at": getattr(opp, "decision_updated_at", None).isoformat() if getattr(opp, "decision_updated_at", None) else None,
    }

    payload_analysis = None
    if analysis:
        payload_analysis = {
            "priority_score": analysis.priority_score,
            "risk_flags": analysis.risk_flags,
            "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else None,
        }

    payload_artifacts = [
        {"id": a.id, "type": a.artifact_type, "title": a.title, "created_at": a.created_at.isoformat(), "content_json": a.content_json}
        for a in artifacts
    ]

    payload_tasks = [
        {"id": t.id, "type": t.task_type, "status": t.status, "due_at": t.due_at.isoformat() if t.due_at else None, "notes": t.notes, "created_at": t.created_at.isoformat()}
        for t in tasks
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("opportunity.json", json.dumps(payload_opp, indent=2))
        z.writestr("analysis.json", json.dumps(payload_analysis, indent=2) if payload_analysis else "null")
        z.writestr("parsed.json", json.dumps(parsed, indent=2))
        z.writestr("decision.txt", f"{payload_opp.get('decision_status')}\n\n{payload_opp.get('decision_note') or ''}".strip())
        z.writestr("raw_text.txt", opp.raw_text or "")
        z.writestr("artifacts.json", json.dumps(payload_artifacts, indent=2))
        z.writestr("tasks.json", json.dumps(payload_tasks, indent=2))

        for a in artifacts:
            if a.artifact_type == "EMAIL_DRAFT" and a.content_json:
                z.writestr("quote_email.txt", f"SUBJECT: {a.content_json.get('subject','')}\n\n{a.content_json.get('body','')}")
            if a.artifact_type == "VENDOR_LIST" and a.content_json:
                vendors = a.content_json.get("vendors") or []
                lines = ["cage,company_name,part_number,contact,email,phone,quoted,unit_price,lead_time_days,notes"]
                for v in vendors:
                    lines.append(",".join([
                        str(v.get("cage") or ""),
                        str(v.get("company_name") or "").replace(",", " "),
                        str(v.get("part_number") or "").replace(",", " "),
                        str(v.get("contact") or "").replace(",", " "),
                        str(v.get("email") or "").replace(",", " "),
                        str(v.get("phone") or "").replace(",", " "),
                        str(v.get("quoted") or False),
                        str(v.get("unit_price") or ""),
                        str(v.get("lead_time_days") or ""),
                        str(v.get("notes") or "").replace(",", " "),
                    ]))
                z.writestr("vendor_shortlist.csv", "\n".join(lines))
            if a.artifact_type == "CHECKLIST" and a.content_json:
                md = [
                    f"# {a.title}",
                    "",
                    f"- NSN: {a.content_json.get('nsn')}",
                    f"- Solicitation: {a.content_json.get('solicitation')}",
                    f"- Due: {a.content_json.get('due_at')}",
                    "",
                    "## Checklist",
                ]
                for item in a.content_json.get("checklist") or []:
                    mark = "x" if item.get("done") else " "
                    md.append(f"- [{mark}] {item.get('text')}")
                z.writestr("checklist.md", "\n".join(md))

    buf.seek(0)
    return buf.read()
