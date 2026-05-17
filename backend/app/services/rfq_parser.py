from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.services.storage import local_temp_path


PDF_PRIORITY = ["PDF_OFFICIAL", "PDF_FALLBACK_SNAPSHOT"]


def _compact_spaces(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _clean_company_name(value: str | None, *, cage: str | None = None, part_number: str | None = None) -> str:
    text = _compact_spaces(value)
    if not text:
        return ""
    if cage:
        cage_match = re.search(rf"\b{re.escape(cage)}\b", text, re.IGNORECASE)
        if cage_match:
            before_cage = _compact_spaces(text[:cage_match.start()])
            if len(before_cage) >= 3:
                text = before_cage
    if part_number:
        part_match = re.search(rf"\b{re.escape(part_number)}\b", text, re.IGNORECASE)
        if part_match:
            before_part = _compact_spaces(text[:part_match.start()])
            if len(before_part) >= 3:
                text = before_part
    text = re.sub(r"\s+[0-9A-Z]{5}\s+[A-Z0-9./_-]{2,80}\b.*$", "", text).strip()
    return text[:200].strip()


def _normalize_nsn(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 13:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:]}"
    return None


def _dedupe_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        cage = _compact_spaces(row.get("cage"))
        part_number = _compact_spaces(row.get("part_number"))
        company_name = _clean_company_name(row.get("company_name"), cage=cage or None, part_number=part_number or None)
        key = (cage.upper(), part_number.upper(), company_name.upper())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "cage": cage or None,
            "part_number": part_number or None,
            "company_name": company_name or None,
        })
    return out


def _read_pdf_text(path: str | Path) -> str:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    try:
        reader = PdfReader(str(p))
    except Exception:
        return ""

    pages: list[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            pages.append(txt)
    return "\n".join(pages).strip()


def _parse_nsn_from_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.lower()
    if "value=" not in u:
        return None
    try:
        q = u.split("?", 1)[1]
        for p in q.split("&"):
            if p.startswith("value="):
                return _normalize_nsn(p.split("=", 1)[1].strip())
    except Exception:
        return None
    return None


def _extract_solicitations(text: str) -> list[dict[str, Any]]:
    lines = [_compact_spaces(ln) for ln in text.splitlines() if _compact_spaces(ln)]
    rows: list[dict[str, Any]] = []
    sol_pat = re.compile(r"^(SPE[A-Z0-9-]+)$")
    date_pat = re.compile(r"^\d{2}-\d{2}-\d{4}$")

    try:
        sidx = lines.index("Solicitations")
    except ValueError:
        sidx = -1
    if sidx == -1:
        return rows

    i = sidx
    while i < len(lines) and lines[i] != "Solicitation #":
        i += 1
    if i >= len(lines):
        return rows

    i += 6
    while i + 5 < len(lines):
        sol = lines[i]
        if sol in {"Policy Statements", "Feedback"}:
            break
        tech = lines[i + 1]
        pr = lines[i + 2]
        qty = lines[i + 3]
        issue = lines[i + 4]
        ret = lines[i + 5]
        if sol_pat.match(sol) and pr.isdigit() and qty.isdigit() and date_pat.match(issue) and date_pat.match(ret):
            rows.append({
                "solicitation": sol,
                "pr": pr,
                "qty": int(qty),
                "issue": issue,
                "return_by": ret,
                "tech_docs": tech if tech != "None" else None,
            })
            i += 6
        else:
            i += 1
    return rows


def _looks_like_header_token(value: str) -> bool:
    v = value.upper()
    return v in {
        "CAGE", "PART NUMBER", "PART NO", "P/N", "COMPANY NAME", "APPROVED SOURCE DATA",
        "MANUFACTURER", "MFR", "NAME", "SOLICITATIONS", "POLICY STATEMENTS", "FEEDBACK"
    }


def _extract_approved_sources_triplets(text: str) -> list[dict[str, Any]]:
    lines = [_compact_spaces(ln) for ln in text.splitlines() if _compact_spaces(ln)]
    rows: list[dict[str, Any]] = []

    start_candidates = [i for i, ln in enumerate(lines) if ln.upper() == "APPROVED SOURCE DATA"]
    for start in start_candidates:
        i = start + 1
        while i < len(lines) and lines[i].upper() != "CAGE":
            i += 1
        if i >= len(lines):
            continue

        i += 1
        while i < len(lines) and _looks_like_header_token(lines[i]):
            i += 1

        while i + 2 < len(lines):
            if lines[i].upper() in {"SOLICITATIONS", "POLICY STATEMENTS", "FEEDBACK"}:
                break
            cage = lines[i]
            part = lines[i + 1]
            company = lines[i + 2]
            if re.fullmatch(r"[0-9A-Z]{5}", cage):
                rows.append({"cage": cage, "part_number": part, "company_name": company})
                i += 3
            else:
                i += 1
    return rows


def _extract_inline_source_patterns(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    flat = _compact_spaces(text)

    pattern_pairs = [
        re.compile(
            r"CAGE\s*[:#-]?\s*(?P<cage>[0-9A-Z]{5})"
            r"(?:.*?)(?:PART\s*(?:NUMBER|NO\.?|#)|P/N)\s*[:#-]?\s*(?P<part>[A-Z0-9./_-]{2,80})"
            r"(?:.*?)(?:COMPANY\s*NAME|MANUFACTURER|MFR|NAME)\s*[:#-]?\s*(?P<company>[^;|]{2,120})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:COMPANY\s*NAME|MANUFACTURER|MFR|NAME)\s*[:#-]?\s*(?P<company>[^;|]{2,120})"
            r"(?:.*?)(?:CAGE)\s*[:#-]?\s*(?P<cage>[0-9A-Z]{5})"
            r"(?:.*?)(?:PART\s*(?:NUMBER|NO\.?|#)|P/N)\s*[:#-]?\s*(?P<part>[A-Z0-9./_-]{2,80})",
            re.IGNORECASE,
        ),
    ]
    for pat in pattern_pairs:
        for m in pat.finditer(flat):
            rows.append({
                "cage": m.group("cage"),
                "part_number": m.group("part"),
                "company_name": m.group("company"),
            })

    # Fallback: capture isolated CAGE values with a nearby company/manufacturer clue.
    line_groups = [grp.strip() for grp in re.split(r"\n\s*\n", text) if grp.strip()]
    for grp in line_groups:
        cage_match = re.search(r"\bCAGE\s*[:#-]?\s*([0-9A-Z]{5})\b", grp, re.IGNORECASE)
        if not cage_match:
            continue
        company_match = re.search(r"(?:COMPANY\s*NAME|MANUFACTURER|MFR|NAME)\s*[:#-]?\s*([^\n]{2,120})", grp, re.IGNORECASE)
        part_match = re.search(r"(?:PART\s*(?:NUMBER|NO\.?|#)|P/N)\s*[:#-]?\s*([^\n ]{2,80})", grp, re.IGNORECASE)
        rows.append({
            "cage": cage_match.group(1),
            "part_number": _compact_spaces(part_match.group(1)) if part_match else None,
            "company_name": _compact_spaces(company_match.group(1)) if company_match else None,
        })

    return rows


def _extract_item_description(text: str) -> str | None:
    patterns = [
        r"\bNomenclature:\s*([^\n]+)",
        r"\bItem Description:\s*([^\n]+)",
        r"\bDescription:\s*([^\n]+)",
        r"\bItem Name:\s*([^\n]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            value = _compact_spaces(m.group(1))
            if value:
                return value
    return None


def _extract_part_numbers(text: str, approved_sources: list[dict[str, Any]]) -> list[str]:
    values = []
    for src in approved_sources:
        part = _compact_spaces(src.get("part_number"))
        if part:
            values.append(part)

    patterns = [
        r"(?:PART\s*(?:NUMBER|NO\.?|#)|P/N)\s*[:#-]?\s*([A-Z0-9./_-]{2,80})",
        r"\bPN\s*[:#-]?\s*([A-Z0-9./_-]{2,80})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            values.append(_compact_spaces(m.group(1)))

    seen = set()
    out = []
    for value in values:
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _matches_nsn(value: str | None, nsn: str | None) -> bool:
    if not value or not nsn:
        return False
    return re.sub(r"\D", "", value) == re.sub(r"\D", "", nsn)


def get_best_opportunity_text(db: Session, opp: Opportunity) -> dict[str, Any]:
    file_rows = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc(), OpportunityFile.id.desc())
        .all()
    )

    for file_type in PDF_PRIORITY:
        matches = [f for f in file_rows if f.file_type == file_type]
        for f in matches:
            if not f.file_path:
                continue
            suffix = Path(f.filename or f.file_path).suffix
            with local_temp_path(f.file_path, suffix=suffix) as local_path:
                text = _read_pdf_text(local_path)
            if text:
                return {
                    "text": text,
                    "source_kind": "pdf",
                    "source_file_type": f.file_type,
                    "source_file_id": f.id,
                    "source_filename": f.filename,
                }

    raw_text = (opp.raw_text or "").strip()
    if raw_text:
        return {
            "text": raw_text,
            "source_kind": "raw_text",
            "source_file_type": None,
            "source_file_id": None,
            "source_filename": None,
        }

    return {
        "text": "",
        "source_kind": None,
        "source_file_type": None,
        "source_file_id": None,
        "source_filename": None,
    }


def parse_dibbs_sources(text: str, url: str | None = None) -> dict[str, Any]:
    approved_sources = _dedupe_sources(
        _extract_approved_sources_triplets(text) + _extract_inline_source_patterns(text)
    )

    nsn = None
    nsn_match = re.search(r"\bNSN\s*[:#-]?\s*([0-9\- ]{13,20})\b", text, re.IGNORECASE)
    if nsn_match:
        nsn = _normalize_nsn(nsn_match.group(1))
    if not nsn:
        nsn = _parse_nsn_from_url(url)

    manufacturers = []
    for src in approved_sources:
        name = _compact_spaces(src.get("company_name"))
        if name and name.upper() not in {m.upper() for m in manufacturers}:
            manufacturers.append(name)

    cages = []
    for src in approved_sources:
        cage = _compact_spaces(src.get("cage"))
        if cage and cage.upper() not in {c.upper() for c in cages}:
            cages.append(cage)

    parsed = {
        "nsn": nsn,
        "nomenclature": _extract_item_description(text),
        "item_description": _extract_item_description(text),
        "approved_sources": approved_sources,
        "approved_source_count": len(approved_sources),
        "manufacturers": manufacturers,
        "cage_codes": cages,
        "part_numbers": [part for part in _extract_part_numbers(text, approved_sources) if not _matches_nsn(part, nsn)],
        "solicitations": _extract_solicitations(text),
    }
    return parsed
