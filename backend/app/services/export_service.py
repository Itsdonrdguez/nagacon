from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.workspace import WorkspaceArtifact
from app.models.vendor import VendorQuote
from app.models.opportunity_file import OpportunityFile


def _safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        s = s.replace(ch, "_")
    return s.strip().replace("  ", " ")


def _artifact_by_type(arts: list[WorkspaceArtifact], artifact_type: str) -> WorkspaceArtifact | None:
    for a in sorted(arts, key=lambda x: x.id, reverse=True):
        if (a.artifact_type or "").upper() == artifact_type.upper():
            return a
    return None


def build_bid_package_zip(db: Session, opportunity_id: int) -> tuple[str, bytes]:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ValueError("Opportunity not found")

    sol = (opp.solicitation_number or f"opportunity_{opp.id}").split("»")[0].strip()
    folder = _safe_filename(sol or f"opportunity_{opp.id}")

    arts = (
        db.query(WorkspaceArtifact)
        .filter(WorkspaceArtifact.opportunity_id == opportunity_id)
        .order_by(WorkspaceArtifact.id.asc())
        .all()
    )
    checklist = _artifact_by_type(arts, "CHECKLIST")
    email = _artifact_by_type(arts, "EMAIL_DRAFT")

    vqs = (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opportunity_id)
        .order_by(VendorQuote.company_name.asc().nullslast(), VendorQuote.cage.asc())
        .all()
    )

    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opportunity_id)
        .order_by(OpportunityFile.id.asc())
        .all()
    )

    now = datetime.utcnow().isoformat()

    opportunity_obj: dict[str, Any] = {
        "id": opp.id,
        "source": opp.source,
        "solicitation_number": opp.solicitation_number,
        "title": opp.title,
        "agency": opp.agency,
        "url": opp.url,
        "posted_at": opp.posted_at.isoformat() if opp.posted_at else None,
        "due_at": opp.due_at.isoformat() if opp.due_at else None,
        "naics": opp.naics,
        "fsc": opp.fsc,
        "set_aside": opp.set_aside,
        "status": getattr(opp, "status", None),
        "exported_at": now,
    }

    parsed_json = getattr(opp, "parsed_json", None)
    parsed_obj = parsed_json if isinstance(parsed_json, (dict, list)) else None

    raw_text = (opp.raw_text or "")

    vendor_shortlist_csv = io.StringIO()
    w = csv.writer(vendor_shortlist_csv)
    w.writerow(["cage", "company_name", "part_number", "contact_name", "email", "phone", "status", "unit_price", "lead_time_days", "notes"])
    for v in vqs:
        w.writerow([
            v.cage,
            v.company_name or "",
            v.part_number or "",
            v.contact_name or "",
            v.email or "",
            v.phone or "",
            v.status or "",
            str(v.unit_price) if v.unit_price is not None else "",
            v.lead_time_days if v.lead_time_days is not None else "",
            (v.notes or "").replace("\n", " ").strip(),
        ])

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        def write(name: str, data: str | bytes):
            arc = f"{folder}/{name}"
            if isinstance(data, str):
                z.writestr(arc, data.encode("utf-8", errors="replace"))
            else:
                z.writestr(arc, data)

        write("opportunity.json", json.dumps(opportunity_obj, indent=2))
        if parsed_obj is not None:
            write("parsed.json", json.dumps(parsed_obj, indent=2))
        write("raw_text.txt", raw_text)

        if checklist and isinstance(checklist.content_json, dict):
            items = checklist.content_json.get("checklist") or []
            md = f"# Bid Checklist - {sol}\n\n"
            for it in items:
                if isinstance(it, dict):
                    md += f"- [ ] {it.get('item') or it.get('text') or json.dumps(it)}\n"
                else:
                    md += f"- [ ] {str(it)}\n"
            write("checklist.md", md)

        if email and isinstance(email.content_json, dict):
            subj = email.content_json.get("subject") or ""
            body = email.content_json.get("body") or ""
            write("email_draft.txt", f"Subject: {subj}\n\n{body}\n")

        write("vendor_shortlist.csv", vendor_shortlist_csv.getvalue())

        # Attach PDFs if downloaded
        for f in files:
            try:
                p = Path(f.file_path)
                if p.exists() and p.is_file():
                    write(f"pdfs/{f.filename}", p.read_bytes())
            except Exception:
                continue

    filename = f"{folder}_bid_package.zip"
    return filename, mem.getvalue()
