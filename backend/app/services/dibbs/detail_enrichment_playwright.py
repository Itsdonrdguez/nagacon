from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.services.dibbs.session import page_html
from app.services.dibbs.structured_detail_parser import parse_dibbs_detail_structured
from app.services.dibbs.approved_source_leads import seed_vendor_leads_from_dibbs_approved_sources


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_rejected(parsed: dict[str, Any]) -> bool:
    title = (parsed.get("detail_title") or "").lower()
    excerpt = (parsed.get("page_excerpt") or "").lower()
    return "request rejected" in title or "requested url was rejected" in excerpt


def is_valid_dibbs_opportunity(parsed: dict[str, Any]) -> bool:
    if not parsed:
        return False

    title = _safe(parsed.get("detail_title")) or ""
    if title != "DIBBS RFQ NSN Page":
        return False

    nsn = _safe(parsed.get("nsn"))
    if not nsn:
        return False

    solicitations = parsed.get("solicitations") or []
    if not solicitations:
        return False

    valid_sol = any(
        _safe(s.get("solicitation_number")) and (_safe(s.get("qty")) or _safe(s.get("return_by_date")))
        for s in solicitations
    )
    return valid_sol


def _build_description(parsed: dict[str, Any]) -> str | None:
    parts: list[str] = []

    nsn = parsed.get("nsn")
    fsc = parsed.get("fsc_code")
    nomenclature = parsed.get("nomenclature")
    approved_sources = parsed.get("approved_sources") or []
    solicitations = parsed.get("solicitations") or []

    if nsn:
        parts.append(f"NSN: {nsn}")
    if fsc:
        parts.append(f"FSC: {fsc}")
    if nomenclature:
        parts.append(f"Item: {nomenclature}")

    if solicitations:
        first_sol = solicitations[0]
        qty = first_sol.get("qty")
        due = first_sol.get("return_by_date")
        pdf = first_sol.get("pdf_url")
        if qty:
            parts.append(f"Qty: {qty}")
        if due:
            parts.append(f"Due: {due}")
        if pdf:
            parts.append(f"PDF: {pdf}")

    if approved_sources:
        first = approved_sources[0]
        company = first.get("company_name")
        part_number = first.get("part_number")
        cage = first.get("cage")

        approved_bits = []
        if company:
            approved_bits.append(company)
        if part_number:
            approved_bits.append(f"P/N {part_number}")
        if cage:
            approved_bits.append(f"CAGE {cage}")

        if approved_bits:
            parts.append("Approved Source: " + ", ".join(approved_bits))

    return " | ".join(parts) if parts else None


def _set_fsc(opportunity: Opportunity, fsc_value: str | None) -> None:
    if not fsc_value:
        return

    if hasattr(opportunity, "fsc_code"):
        setattr(opportunity, "fsc_code", fsc_value)
    elif hasattr(opportunity, "fsc"):
        setattr(opportunity, "fsc", fsc_value)
    elif hasattr(opportunity, "fsc_id"):
        setattr(opportunity, "fsc_id", fsc_value)


def _get_fsc(opportunity: Opportunity) -> str | None:
    if hasattr(opportunity, "fsc_code"):
        return getattr(opportunity, "fsc_code")
    if hasattr(opportunity, "fsc"):
        return getattr(opportunity, "fsc")
    if hasattr(opportunity, "fsc_id"):
        return getattr(opportunity, "fsc_id")
    return None


def _set_due_at(opportunity: Opportunity, value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%m-%d-%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(value, fmt)
            opportunity.due_at = dt
            return dt.isoformat()
        except Exception:
            continue
    return None


def _select_matching_solicitation(opportunity: Opportunity, parsed: dict[str, Any]) -> dict[str, Any] | None:
    solicitation_number = _safe(getattr(opportunity, "solicitation_number", None))
    if not solicitation_number:
        solicitation_number = _safe(getattr(opportunity, "source_opportunity_id", None))
    solicitations = parsed.get("solicitations") or []
    if not solicitations:
        return None

    if not solicitation_number:
        return solicitations[0]

    compact = solicitation_number.replace("-", "").upper()
    for row in solicitations:
        sol = _safe(row.get("solicitation_number"))
        if not sol:
            continue
        if sol.replace("-", "").upper() == compact:
            return row
    return solicitations[0]


def enrich_dibbs_opportunity(
    db: Session,
    opportunity: Opportunity,
    debug: bool = False,
    auto_seed_approved_sources: bool = True,
) -> dict[str, Any]:
    url = _safe(getattr(opportunity, "url", None))
    if not url:
        return {"ok": False, "error": "Opportunity has no URL"}

    html = page_html(url, headless=not debug)
    parsed = parse_dibbs_detail_structured(html, url)

    if _is_rejected(parsed):
        return {
            "ok": False,
            "opportunity_id": opportunity.id,
            "error": "DIBBS request rejected (even with Playwright)",
            "parsed": parsed,
        }

    if not is_valid_dibbs_opportunity(parsed):
        return {
            "ok": False,
            "opportunity_id": opportunity.id,
            "error": "Skipped non-opportunity DIBBS navigation/search page",
            "parsed": parsed,
        }

    raw_payload = dict(getattr(opportunity, "raw_payload", None) or {})
    raw_payload["dibbs_detail"] = parsed

    _set_fsc(opportunity, parsed.get("fsc_code"))

    if parsed.get("nsn"):
        raw_payload["dibbs_nsn"] = parsed.get("nsn")

    selected_row = _select_matching_solicitation(opportunity, parsed)
    updated_due_at = None
    updated_pdf_url = None
    updated_qty = None

    if selected_row:
        updated_due_at = _set_due_at(opportunity, _safe(selected_row.get("return_by_date")))
        updated_pdf_url = _safe(selected_row.get("pdf_url"))
        updated_qty = _safe(selected_row.get("qty"))
        raw_payload["dibbs_selected_solicitation"] = selected_row

    built_description = _build_description(parsed)
    if built_description:
        opportunity.description = built_description

    if parsed.get("nsn"):
        opportunity.source_opportunity_id = parsed.get("nsn")
    elif not getattr(opportunity, "source_opportunity_id", None) and getattr(opportunity, "solicitation_number", None):
        opportunity.source_opportunity_id = opportunity.solicitation_number

    opportunity.raw_payload = raw_payload
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)

    out = {
        "ok": True,
        "opportunity_id": opportunity.id,
        "url": url,
        "parsed": parsed,
        "updated_fields": {
            "source_opportunity_id": getattr(opportunity, "source_opportunity_id", None),
            "fsc_code": _get_fsc(opportunity),
            "description": getattr(opportunity, "description", None),
            "due_at": updated_due_at,
            "solicitation_pdf_url": updated_pdf_url,
            "qty": updated_qty,
            "workspace_url": getattr(opportunity, "workspace_url", None),
            "workspace_api_url": getattr(opportunity, "workspace_api_url", None),
        },
    }

    if auto_seed_approved_sources:
        seed_result = seed_vendor_leads_from_dibbs_approved_sources(db=db, opportunity_id=opportunity.id)
        out["approved_source_seed"] = seed_result

    return out


def enrich_dibbs_batch(
    db: Session,
    limit: int = 10,
    source: str = "DIBBS",
    debug: bool = False,
    auto_seed_approved_sources: bool = True,
) -> dict[str, Any]:
    rows = (
        db.query(Opportunity)
        .filter(Opportunity.source == source)
        .order_by(Opportunity.id.desc())
        .limit(limit)
        .all()
    )

    results = []
    enriched = 0
    failed = 0
    total_seed_created = 0
    total_seed_updated = 0

    for opp in rows:
        try:
            out = enrich_dibbs_opportunity(
                db,
                opp,
                debug=debug,
                auto_seed_approved_sources=auto_seed_approved_sources,
            )
            results.append(out)
            if out.get("ok"):
                enriched += 1
                seed_block = out.get("approved_source_seed") or {}
                total_seed_created += int(seed_block.get("created", 0) or 0)
                total_seed_updated += int(seed_block.get("updated", 0) or 0)
            else:
                failed += 1
        except Exception as e:
            failed += 1
            results.append({"ok": False, "opportunity_id": opp.id, "error": str(e)})

    return {
        "source": source,
        "requested_limit": limit,
        "enriched": enriched,
        "failed": failed,
        "auto_seed_approved_sources": auto_seed_approved_sources,
        "approved_source_seed_summary": {
            "created": total_seed_created,
            "updated": total_seed_updated,
        },
        "results": results,
    }
