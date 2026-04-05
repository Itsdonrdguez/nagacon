from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity, OpportunityAnalysis
from app.models.workspace import WorkspaceArtifact, WorkspaceTask
from app.services.rfq_parser import get_best_opportunity_text, parse_dibbs_sources
from app.services.vendor_service import sync_vendor_leads_from_parsed


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


def parse_dibbs_raw_text(raw_text: str) -> dict[str, Any]:
    return parse_dibbs_sources(raw_text)


def ensure_parsed(db: Session, opp: Opportunity) -> dict[str, Any]:
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
) -> WorkspaceArtifact:
    rec = WorkspaceArtifact(
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


def generate_checklist(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    nsn = parsed.get("nsn")
    sol = opp.solicitation_number or ""
    due = opp.due_at.isoformat() if opp.due_at else None

    items = [
        {"id": "confirm_row", "text": "Confirm you are bidding the correct solicitation row for this NSN.", "done": False},
        {"id": "download_docs", "text": "Download/verify technical documents (if any).", "done": False},
        {"id": "approved_sources", "text": "Review approved sources list; pick supplier(s) to quote.", "done": False},
        {"id": "pricing_inputs", "text": "Collect pricing inputs (qty, shipping, lead time, payment terms).", "done": False},
        {"id": "compliance", "text": "Review solicitation requirements / DFARS-FAR clauses on page.", "done": False},
        {"id": "submit_quote", "text": "Prepare and submit quote before due date.", "done": False},
    ]

    content = {"nsn": nsn, "solicitation": sol, "due_at": due, "checklist": items}
    return create_artifact(db, opp.id, "CHECKLIST", f"Bid Checklist - {sol}", content_json=content)


def generate_vendor_shortlist(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    sync_stats = sync_vendor_leads_from_parsed(db, opp)
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
        "vendors": vendors,
    }
    sol = opp.solicitation_number or ""
    return create_artifact(db, opp.id, "VENDOR_LIST", f"Vendor Shortlist - {sol}", content_json=content)


def generate_quote_email(db: Session, opp: Opportunity) -> WorkspaceArtifact:
    parsed = ensure_parsed(db, opp)
    nsn = parsed.get("nsn") or ""
    sol = opp.solicitation_number or ""
    qty = None

    sol_key = re.sub(r"[^A-Za-z0-9]+", "", sol.upper())
    for r in parsed.get("solicitations") or []:
        if r.get("solicitation") == sol_key:
            qty = r.get("qty")
            break

    subject = f"RFQ Quote Request - NSN {nsn} - {sol}".strip()
    body = (
        "Hello,\n\n"
        "Please provide a quote for the following item:\n"
        f"- NSN: {nsn}\n"
        f"- Solicitation: {sol}\n"
        f"- Quantity: {qty if qty is not None else '[QTY]'}\n\n"
        "Please include:\n"
        "- Unit price and total price\n"
        "- Lead time / availability\n"
        "- Shipping cost (FOB destination if applicable)\n"
        "- Payment terms\n\n"
        "Thank you,\n"
        "[Your Name]\n"
        "[Company]\n"
        "[Phone]\n"
        "[Email]\n"
    )
    content = {"subject": subject, "body": body, "nsn": nsn}
    return create_artifact(db, opp.id, "EMAIL_DRAFT", f"Quote Email Draft - {sol}", content_json=content)


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
