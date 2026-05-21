from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.repositories.providers import ProviderRepository
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.provider import Provider, ProviderItem
from app.models.vendor import VendorLead
from app.schemas.provider import ProviderCreate, ProviderItemCreate, ProviderPdfExtractResult
from app.services.dibbs.pdf_bulk_export import LATEST_MANIFEST_REF
from app.services.document_parser import parse_opportunity_file
from app.services.provider_settings_service import get_effective_sam_api_key, get_sam_api_key_candidates
from app.services.rfq_parser import parse_dibbs_sources
from app.services.storage import file_exists, local_temp_path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
EXPORT_ROOT = BACKEND_ROOT / "exports" / "dibbs_pdfs"
SAM_ENTITY_URL = "https://api.sam.gov/entity-information/v3/entities"
BLOCKED_CAGE_TOKENS = {
    "CODES",
    "CONTR",
    "CAGEC",
    "DODAAC",
    "EMAIL",
    "ISSUE",
    "NAME",
    "PHONE",
    "TABLE",
}
BLOCKED_COMPANY_TOKENS = {
    "SOLICITATIONS",
    "SOLICITATION",
    "POLICY STATEMENTS",
    "POLICY STATEMENTS FEEDBACK",
    "FEEDBACK",
    "APPROVED SOURCE DATA",
    "TECHNICAL DOCUMENTS",
}


def _clean(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return None
    return text[:max_len] if max_len else text


def _normalize_cage(value: str | None) -> str | None:
    text = _clean(value, 20)
    if not text:
        return None
    text = text.upper()
    if text in BLOCKED_CAGE_TOKENS:
        return None
    if not re.fullmatch(r"[0-9A-Z]{5}", text):
        return None
    # DIBBS RFQ text contains many five-letter headers. Requiring at least one
    # digit removes most false positives while keeping normal CAGE values.
    if not any(char.isdigit() for char in text):
        return None
    return text


def _normalize_nsn(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 13:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:]}"
    return None


def _compact_nsn(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _nsn_from_filename(path: Path) -> str | None:
    match = re.search(r"(\d{4})[-_ ]?(\d{2})[-_ ]?(\d{3})[-_ ]?(\d{4})", path.stem)
    if not match:
        return None
    return _normalize_nsn("".join(match.groups()))


def _nsn_from_opportunity(opp: Opportunity) -> str | None:
    parsed = getattr(opp, "parsed_json", None) or {}
    for candidate in [
        parsed.get("nsn") if isinstance(parsed, dict) else None,
        getattr(opp, "source_opportunity_id", None),
        getattr(opp, "solicitation_number", None),
        getattr(opp, "title", None),
        getattr(opp, "raw_text", None),
    ]:
        normalized = _normalize_nsn(candidate)
        if normalized:
            return normalized
    return None


def _fsc_from_path(path: Path, nsn: str | None) -> str | None:
    if nsn:
        return nsn[:4]
    for part in reversed(path.parts):
        if re.fullmatch(r"\d{4}", part):
            return part
    return None


def _nomenclature_from_path(path: Path) -> str | None:
    stem = path.stem
    stem = re.sub(r"^SPE[A-Z0-9]+[-_A-Z0-9]*", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\d{4}[-_ ]?\d{2}[-_ ]?\d{3}[-_ ]?\d{4}", "", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    return _clean(stem, 300)


def _nomenclature_for_provider(parsed: dict[str, Any], path: Path, opp: Opportunity | None = None) -> str | None:
    for candidate in [
        parsed.get("nomenclature"),
        parsed.get("item_description"),
        getattr(opp, "title", None) if opp else None,
        _nomenclature_from_path(path),
    ]:
        value = _clean(candidate, 300)
        if value:
            return value
    return None


def backfill_dibbs_provider_item_nomenclature(db: Session, *, organization_id: int | None = None) -> dict[str, int]:
    query = (
        db.query(ProviderItem)
        .join(Provider, Provider.id == ProviderItem.provider_id)
        .filter(ProviderItem.nsn.is_not(None))
        .filter((ProviderItem.nomenclature.is_(None)) | (ProviderItem.nomenclature == ""))
        .filter(ProviderItem.source.in_(["DIBBS Solicitation PDF", "DIBBS Opportunity PDF", "DIBBS Approved Source"]))
    )
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)

    updated = 0
    checked = 0
    for item in query.all():
        checked += 1
        opp = (
            db.query(Opportunity)
            .filter(
                (Opportunity.solicitation_number == item.nsn)
                | (Opportunity.source_opportunity_id == item.nsn)
                | (Opportunity.title.ilike(f"%{item.nsn}%"))
                | (Opportunity.raw_text.ilike(f"%{item.nsn}%"))
            )
            .order_by(Opportunity.id.desc())
            .first()
        )
        name = _clean(getattr(opp, "title", None), 300) if opp else None
        if name:
            item.nomenclature = name
            db.add(item)
            updated += 1
    if updated:
        db.commit()
    return {"checked": checked, "updated": updated}


def enrich_provider_websites_from_sam(
    db: Session,
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
    limit: int = 250,
) -> dict[str, Any]:
    api_key = get_effective_sam_api_key(db, user_id=user_id)
    if not api_key:
        return {"checked": 0, "updated": 0, "missing_api_key": True, "errors": ["SAM API key is not configured."]}

    query = db.query(Provider).filter(Provider.cage.is_not(None))
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)
    providers = query.order_by(Provider.updated_at.desc(), Provider.id.desc()).limit(max(min(limit, 1000), 1)).all()

    checked = 0
    updated = 0
    errors: list[str] = []
    for provider in providers:
        cage = _normalize_cage(provider.cage)
        if not cage:
            continue
        checked += 1
        sam_row = _lookup_sam_entity(cage, api_key)
        if sam_row.get("error"):
            errors.append(f"CAGE {cage}: SAM lookup failed - {sam_row['error']}")
            continue
        sam_name = _clean(sam_row.get("company_name"), 240)
        sam_website = _normalize_website(sam_row.get("website"))
        touched = False
        if sam_name and provider.company_name != sam_name:
            provider.company_name = sam_name
            touched = True
        if sam_website and provider.website != sam_website:
            provider.website = sam_website
            touched = True
        if touched:
            db.add(provider)
            updated += 1
        elif not sam_row:
            errors.append(f"CAGE {cage}: no SAM entity match returned.")

    if updated:
        db.commit()
    return {"checked": checked, "updated": updated, "missing_api_key": False, "errors": errors[:10]}


def _is_valid_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _first_string(node: Any, keys: set[str]) -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in node.values():
            found = _first_string(value, keys)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _first_string(item, keys)
            if found:
                return found
    return None


def _normalize_website(value: str | None) -> str | None:
    text = _clean(value, 500)
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    if "@" in text or " " in text:
        return None
    if not re.match(r"^https?://", text, flags=re.IGNORECASE):
        text = f"https://{text}"
    return text


def _normalize_company_name(value: str | None, *, cage: str | None = None) -> str | None:
    text = _clean(value, 240)
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text).strip().upper()
    if compact in BLOCKED_COMPANY_TOKENS:
        return None
    if cage and compact == f"CAGE {cage}".upper():
        return None
    if re.fullmatch(r"(SOLICITATION|SOLICITATIONS)(\s+[A-Z0-9#-]+)?", compact):
        return None
    if len(compact) <= 3:
        return None
    return text


@lru_cache(maxsize=512)
def _lookup_sam_entity(cage: str, api_key: str) -> dict[str, str | None]:
    if not cage or not api_key:
        return {}
    try:
        response = requests.get(
            SAM_ENTITY_URL,
            params={"api_key": api_key, "cageCode": cage, "includeSections": "entityRegistration,coreData"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return {
            "error": f"{exc.__class__.__name__}: {str(exc)[:300]}",
            "error_status": str(status_code) if status_code is not None else None,
        }

    name = _first_string(payload, {"legalBusinessName", "entityName", "businessName"})
    website = _first_string(payload, {"entityURL", "entityUrl", "website", "websiteUrl", "websiteURL", "businessURL"})
    return {
        "company_name": _clean(name, 240),
        "website": _normalize_website(website),
    }


def _lookup_sam_entity_with_fallback(cage: str, api_keys: list[tuple[str, str]]) -> tuple[dict[str, str | None], str | None]:
    last_error: dict[str, str | None] | None = None
    last_source: str | None = None
    for source, api_key in api_keys:
        row = _lookup_sam_entity(cage, api_key)
        if not row.get("error"):
            row["api_key_source"] = source
            return row, source
        last_error = row
        last_source = source
        if str(row.get("error_status") or "") not in {"401", "403"}:
            row["api_key_source"] = source
            return row, source
    if last_error is None:
        return {}, None
    last_error["api_key_source"] = last_source
    return last_error, last_source


def _approved_source_rows(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source in parsed.get("approved_sources") or []:
        cage = _normalize_cage(source.get("cage"))
        if not cage:
            continue
        rows.append({
            "cage": cage,
            "company_name": _clean(source.get("company_name"), 240),
            "part_number": _clean(source.get("part_number"), 120),
            "relationship_type": "Approved Source",
        })
    if rows:
        return rows
    return [
        {
            "cage": cage,
            "company_name": None,
            "part_number": None,
            "relationship_type": "Unknown",
        }
        for cage in [_normalize_cage(cage) for cage in parsed.get("cage_codes") or []]
        if cage
    ]


def _manufacturer_rows_from_text(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    patterns = [
        re.compile(
            r"(?P<name>[A-Z][A-Z0-9 .,&'()/\-]{2,90}?)\s+"
            r"(?P<cage>[0-9][0-9A-Z]{4})\s+"
            r"(?:P/N|PN|PART\s*(?:NO\.?|NUMBER))\s*[:#-]?\s*(?P<part>[A-Z0-9./_-]{2,80})",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:MFG|MANUFACTURER)\s*[:#-]?\s*(?P<name>[A-Z][A-Z0-9 .,&'()/\-]{2,90}?)\s+"
            r"(?P<cage>[0-9][0-9A-Z]{4})\b"
            r"(?:.*?(?:P/N|PN|PART\s*(?:NO\.?|NUMBER))\s*[:#-]?\s*(?P<part>[A-Z0-9./_-]{2,80}))?",
            re.IGNORECASE,
        ),
    ]
    for line in [_clean(line, 240) for line in text.splitlines()]:
        if not line:
            continue
        for pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            cage = _normalize_cage(match.group("cage"))
            name = _clean(match.group("name"), 240)
            part = _clean(match.groupdict().get("part"), 120)
            if not cage or not name:
                continue
            name = re.sub(r"^(MFG|MANUFACTURER)\s*[:#-]?\s*", "", name, flags=re.IGNORECASE).strip()
            if len(re.findall(r"\b[0-9][0-9A-Z]{4}\b", name)) > 1:
                continue
            key = (cage, part, name.upper())
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "cage": cage,
                "company_name": name,
                "part_number": part,
                "relationship_type": "Manufacturer",
            })
    return rows


def _part_number_from_notes(notes: str | None) -> str | None:
    match = re.search(r"\bPart number:\s*([^;]+)", notes or "", re.IGNORECASE)
    return _clean(match.group(1), 80) if match else None


def _sanitize_part_number(part_number: str | None, *, nsn: str | None = None) -> str | None:
    clean = _clean(part_number, 80)
    if not clean:
        return None
    compact = _compact_nsn(clean)
    if len(compact) == 13 and nsn and compact == _compact_nsn(nsn):
        return None
    return clean


def _upsert_vendor_lead_from_provider(
    db: Session,
    *,
    opp: Opportunity,
    company_name: str | None,
    cage: str | None,
    nsn: str | None,
    part_number: str | None,
    source_type: str,
    notes: str | None,
    confidence: int,
    is_approved_source: bool,
) -> tuple[bool, bool]:
    cage = _normalize_cage(cage)
    company_name = _clean(company_name, 200)
    part_number = _sanitize_part_number(part_number, nsn=nsn)
    if not cage and not company_name:
        return False, False

    for pending in db.new:
        if not isinstance(pending, VendorLead):
            continue
        if getattr(pending, "opportunity_id", None) != opp.id:
            continue
        if _normalize_cage(getattr(pending, "cage", None)) != cage:
            continue
        if _clean(getattr(pending, "part_number", None), 80) != part_number:
            continue
        if company_name and getattr(pending, "company_name", None) != company_name:
            pending.company_name = company_name
        if nsn and not getattr(pending, "nsn", None):
            pending.nsn = nsn
        if notes and not getattr(pending, "notes", None):
            pending.notes = notes
            pending.raw_text = notes
        if confidence > (getattr(pending, "confidence", None) or 0):
            pending.confidence = confidence
        if is_approved_source and not getattr(pending, "is_approved_source", False):
            pending.is_approved_source = True
        if source_type and getattr(pending, "source_type", None) in {"UNKNOWN", "PROVIDER_DATABASE", "DIBBS_PDF_PROVIDER"}:
            pending.source_type = source_type
        pending.updated_at = datetime.utcnow()
        return False, True

    query = db.query(VendorLead).filter(VendorLead.opportunity_id == opp.id)
    query = query.filter(VendorLead.cage == cage) if cage else query.filter(VendorLead.cage.is_(None))
    query = query.filter(VendorLead.part_number == part_number) if part_number else query.filter(VendorLead.part_number.is_(None))
    existing = query.first()

    if not existing:
        fallback_query = db.query(VendorLead).filter(VendorLead.opportunity_id == opp.id)
        if cage:
            fallback_query = fallback_query.filter(VendorLead.cage == cage)
        elif company_name:
            fallback_query = fallback_query.filter(VendorLead.company_name == company_name)
        else:
            fallback_query = fallback_query.filter(VendorLead.cage.is_(None))
        if nsn:
            fallback_query = fallback_query.filter(or_(VendorLead.nsn == nsn, VendorLead.nsn.is_(None)))
        existing = (
            fallback_query
            .order_by(VendorLead.part_number.is_(None), VendorLead.confidence.desc().nullslast(), VendorLead.id.desc())
            .first()
        )

    if existing:
        touched = False
        if getattr(opp, "organization_id", None) is not None and existing.organization_id is None:
            existing.organization_id = getattr(opp, "organization_id", None)
            touched = True
        if company_name and not existing.company_name:
            existing.company_name = company_name
            touched = True
        elif company_name and existing.company_name != company_name:
            existing.company_name = company_name
            touched = True
        if nsn and not existing.nsn:
            existing.nsn = nsn
            touched = True
        if notes and not existing.notes:
            existing.notes = notes
            touched = True
        if confidence > (existing.confidence or 0):
            existing.confidence = confidence
            touched = True
        if is_approved_source and not existing.is_approved_source:
            existing.is_approved_source = True
            touched = True
        if source_type and existing.source_type in {"UNKNOWN", "PROVIDER_DATABASE"}:
            existing.source_type = source_type
            touched = True
        if touched:
            existing.updated_at = datetime.utcnow()
            db.add(existing)
            return False, True
        return False, False

    db.add(VendorLead(
        organization_id=getattr(opp, "organization_id", None),
        opportunity_id=opp.id,
        source_type=source_type,
        company_name=company_name,
        cage=cage,
        part_number=part_number,
        nsn=nsn,
        status="NEW",
        confidence=confidence,
        is_approved_source=is_approved_source,
        raw_text=notes,
        notes=notes,
    ))
    return True, False


def extract_providers_from_dibbs_pdfs(
    db: Session,
    *,
    organization_id: int | None = None,
    user_id: int | None = None,
    root: Path | str = EXPORT_ROOT,
    enrich_with_sam: bool = True,
    limit: int | None = None,
) -> ProviderPdfExtractResult:
    result = ProviderPdfExtractResult()
    base = Path(root)

    repo = ProviderRepository(db, organization_id=organization_id)
    sam_api_keys = get_sam_api_key_candidates(db, user_id=user_id) if enrich_with_sam else []
    seen_cage_item: set[tuple[str, str | None, str]] = set()
    if base.exists():
        pdf_paths = sorted(base.rglob("*.pdf"))
        if limit:
            pdf_paths = pdf_paths[: max(limit, 0)]
        for path in pdf_paths:
            _extract_provider_rows_from_pdf(
                db,
                repo=repo,
                sam_api_keys=sam_api_keys,
                result=result,
                seen_cage_item=seen_cage_item,
                reference=str(path),
                display_name=path.name,
            )
        return result

    if not file_exists(LATEST_MANIFEST_REF):
        result.errors.append(f"PDF export folder does not exist: {base}")
        return result

    try:
        with local_temp_path(LATEST_MANIFEST_REF, suffix=".json") as manifest_meta_path:
            manifest_meta = json.loads(manifest_meta_path.read_text(encoding="utf-8"))
        manifest_ref = manifest_meta.get("manifest_jsonl")
        if not manifest_ref or not file_exists(manifest_ref):
            result.errors.append("The latest DIBBS PDF manifest was not found in shared storage.")
            return result
        with local_temp_path(manifest_ref, suffix=".jsonl") as manifest_path:
            count = 0
            for line in manifest_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("status") != "downloaded" or not row.get("file_path"):
                    continue
                _extract_provider_rows_from_pdf(
                    db,
                    repo=repo,
                    sam_api_keys=sam_api_keys,
                    result=result,
                    seen_cage_item=seen_cage_item,
                    reference=row["file_path"],
                    display_name=Path(str(row["file_path"])).name,
                    nsn_hint=_normalize_nsn(row.get("nsn")),
                    fsc_hint=_clean(row.get("fsc")) or _fsc_from_path(Path(str(row["file_path"])), _normalize_nsn(row.get("nsn"))),
                    nomenclature_hint=_clean(row.get("nomenclature"), 300),
                )
                count += 1
                if limit and count >= max(limit, 0):
                    break
    except Exception as exc:
        result.errors.append(f"Could not read shared DIBBS PDF manifest: {exc}")

    return result


def _extract_provider_rows_from_pdf(
    db: Session,
    *,
    repo: ProviderRepository,
    sam_api_keys: list[tuple[str, str]],
    result: ProviderPdfExtractResult,
    seen_cage_item: set[tuple[str, str | None, str]],
    reference: str,
    display_name: str,
    nsn_hint: str | None = None,
    fsc_hint: str | None = None,
    nomenclature_hint: str | None = None,
) -> None:
    result.scanned_files += 1
    with local_temp_path(reference, suffix=Path(display_name).suffix or ".pdf") as path:
        if not path.exists() or not _is_valid_pdf(path):
            result.invalid_pdfs += 1
            result.skipped += 1
            return

        result.valid_pdfs += 1
        parsed_doc = parse_opportunity_file(str(path))
        text = parsed_doc.get("text") or ""
        parsed = parse_dibbs_sources(text)
        nsn = parsed.get("nsn") or nsn_hint or _nsn_from_filename(path)
        fsc = fsc_hint or _fsc_from_path(path, nsn)
        nomenclature = _nomenclature_for_provider(parsed, path) or nomenclature_hint
        rows = _approved_source_rows(parsed) + _manufacturer_rows_from_text(text)

        if not rows:
            result.skipped += 1
            return

        for row in rows:
            cage = row["cage"]
            result.cages_found += 1
            key = (cage, nsn, row["relationship_type"])
            if key in seen_cage_item:
                result.skipped += 1
                continue
            seen_cage_item.add(key)

            company_name = _normalize_company_name(row.get("company_name"), cage=cage)
            sam_website = None
            if sam_api_keys:
                sam_row, sam_source = _lookup_sam_entity_with_fallback(cage, sam_api_keys)
                if sam_row.get("error"):
                    source_label = f" ({sam_source} key)" if sam_source else ""
                    result.errors.append(f"{display_name} / CAGE {cage}: SAM lookup failed{source_label} - {sam_row['error']}")
                    sam_row = {}
                sam_name = _normalize_company_name(sam_row.get("company_name"), cage=cage)
                sam_website = sam_row.get("website")
                if sam_name:
                    company_name = sam_name
                    result.sam_enriched += 1
                elif not company_name:
                    result.sam_misses += 1

            company_name = company_name or f"CAGE {cage}"
            notes = []
            if row.get("part_number"):
                notes.append(f"Part number: {row['part_number']}")
            notes.append(f"Extracted from {display_name}")

            payload = ProviderCreate(
                company_name=company_name,
                cage=cage,
                website=sam_website if sam_api_keys else None,
                notes="; ".join(notes),
                item=ProviderItemCreate(
                    nsn=nsn,
                    fsc=fsc,
                    nomenclature=nomenclature,
                    relationship_type=row["relationship_type"],
                    source="DIBBS Solicitation PDF",
                    source_url=reference,
                    confidence=95 if row["relationship_type"] == "Approved Source" else 65,
                    notes="; ".join(notes),
                ),
            )
            existing = repo._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
            try:
                repo.create(payload)
                if existing:
                    result.updated += 1
                else:
                    result.inserted += 1
            except Exception as exc:
                db.rollback()
                result.errors.append(f"{display_name} / CAGE {cage}: {exc}")


def seed_vendor_leads_from_providers(
    db: Session,
    opp: Opportunity,
    *,
    parsed: dict[str, Any] | None = None,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, int]:
    parsed = parsed or getattr(opp, "parsed_json", None) or {}
    nsn = _normalize_nsn(parsed.get("nsn") if isinstance(parsed, dict) else None) or _nsn_from_opportunity(opp)
    parsed_cages = {
        cage
        for cage in [_normalize_cage(value) for value in ((parsed.get("cage_codes") if isinstance(parsed, dict) else []) or [])]
        if cage
    }
    for source in (parsed.get("approved_sources") if isinstance(parsed, dict) else []) or []:
        cage = _normalize_cage(source.get("cage"))
        if cage:
            parsed_cages.add(cage)

    query = db.query(Provider, ProviderItem).join(ProviderItem, ProviderItem.provider_id == Provider.id)
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)
    filters = []
    if nsn:
        filters.append(ProviderItem.nsn == nsn)
    if parsed_cages:
        filters.append(Provider.cage.in_(parsed_cages))
    if not filters:
        return {"created": 0, "updated": 0, "matched": 0}

    sam_api_key = get_effective_sam_api_key(db, user_id=user_id)
    sam_api_keys = get_sam_api_key_candidates(db, user_id=user_id)
    rows = query.filter(or_(*filters)).order_by(ProviderItem.confidence.desc().nullslast(), Provider.company_name.asc()).all()
    created = 0
    updated = 0
    matched = 0
    seen: set[tuple[str | None, str | None]] = set()
    for provider, item in rows:
        cage = _normalize_cage(provider.cage)
        if cage and sam_api_key and sam_api_keys:
            sam_row, _ = _lookup_sam_entity_with_fallback(cage, sam_api_keys)
            sam_name = _clean(sam_row.get("company_name"), 240)
            sam_website = _normalize_website(sam_row.get("website"))
            if sam_name and provider.company_name != sam_name:
                provider.company_name = sam_name
                db.add(provider)
            if sam_website and not provider.website:
                provider.website = sam_website
                db.add(provider)
        part_number = _sanitize_part_number(_part_number_from_notes(item.notes), nsn=nsn or item.nsn)
        key = (cage, part_number)
        if key in seen:
            continue
        seen.add(key)
        matched += 1
        exact_nsn = bool(nsn and item.nsn == nsn)
        explicit_cage = bool(cage and cage in parsed_cages)
        relationship = item.relationship_type or "Provider"
        source_type = "PROVIDER_NSN_MATCH" if exact_nsn else "PROVIDER_CAGE_MATCH"
        is_approved = relationship.upper() == "APPROVED SOURCE" or "APPROVED" in (item.source or "").upper()
        confidence = int(min(99, max(60, item.confidence or 70) + (5 if exact_nsn else 0) + (5 if explicit_cage else 0)))
        notes = "; ".join([
            value for value in [
                f"Matched from Providers database ({item.source or 'Provider record'})",
                f"Type: {relationship}",
                f"NSN: {item.nsn}" if item.nsn else None,
                f"FSC: {item.fsc}" if item.fsc else None,
                f"Item: {item.nomenclature}" if item.nomenclature else None,
                item.notes,
            ]
            if value
        ])
        was_created, was_updated = _upsert_vendor_lead_from_provider(
            db,
            opp=opp,
            company_name=provider.company_name,
            cage=cage,
            nsn=nsn or item.nsn,
            part_number=part_number,
            source_type=source_type,
            notes=notes,
            confidence=confidence,
            is_approved_source=is_approved,
        )
        created += 1 if was_created else 0
        updated += 1 if was_updated else 0

    if created or updated:
        db.commit()
    return {"created": created, "updated": updated, "matched": matched}


def extract_providers_from_opportunity_pdfs(
    db: Session,
    opp: Opportunity,
    *,
    enrich_with_sam: bool = True,
    organization_id: int | None = None,
    user_id: int | None = None,
) -> ProviderPdfExtractResult:
    result = ProviderPdfExtractResult()
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc(), OpportunityFile.id.desc())
        .all()
    )
    if organization_id is not None:
        files = [file for file in files if file.organization_id in {organization_id, None}]
    if not files:
        result.errors.append("No opportunity files are available for provider extraction.")
        return result

    repo = ProviderRepository(db, organization_id=organization_id)
    sam_api_keys = get_sam_api_key_candidates(db, user_id=user_id) if enrich_with_sam else []
    seen_cage_item: set[tuple[str, str | None, str]] = set()

    for file_record in files:
        reference = file_record.file_path or ""
        filename = file_record.filename or Path(reference).name
        if Path(filename).suffix.lower() != ".pdf":
            continue
        result.scanned_files += 1
        with local_temp_path(reference, suffix=Path(filename).suffix) as path:
            if not path.exists() or not _is_valid_pdf(path):
                result.invalid_pdfs += 1
                result.skipped += 1
                continue

            result.valid_pdfs += 1
            text = file_record.extracted_text or (parse_opportunity_file(str(path)).get("text") or "")
            parsed = parse_dibbs_sources(text, file_record.source_url)
            nsn = parsed.get("nsn") or _nsn_from_filename(path) or _nsn_from_opportunity(opp)
            fsc = _fsc_from_path(path, nsn) or getattr(opp, "fsc", None)
            nomenclature = _nomenclature_for_provider(parsed, path, opp)
            rows = _approved_source_rows(parsed) + _manufacturer_rows_from_text(text)

            if not rows:
                result.skipped += 1
                continue

            for row in rows:
                cage = row["cage"]
                result.cages_found += 1
                key = (cage, nsn, row["relationship_type"])
                if key in seen_cage_item:
                    result.skipped += 1
                    continue
                seen_cage_item.add(key)

                company_name = _normalize_company_name(row.get("company_name"), cage=cage)
                sam_website = None
                if sam_api_keys:
                    sam_row, sam_source = _lookup_sam_entity_with_fallback(cage, sam_api_keys)
                    if sam_row.get("error"):
                        source_label = f" ({sam_source} key)" if sam_source else ""
                        result.errors.append(f"{filename or path.name} / CAGE {cage}: SAM lookup failed{source_label} - {sam_row['error']}")
                        sam_row = {}
                    sam_name = _normalize_company_name(sam_row.get("company_name"), cage=cage)
                    sam_website = sam_row.get("website")
                    if sam_name:
                        company_name = sam_name
                        result.sam_enriched += 1
                    elif not company_name:
                        result.sam_misses += 1
                company_name = company_name or f"CAGE {cage}"
                notes = []
                if row.get("part_number"):
                    notes.append(f"Part number: {row['part_number']}")
                notes.append(f"Extracted from {filename or path.name}")
                source = "DIBBS Opportunity PDF"
                payload = ProviderCreate(
                    company_name=company_name,
                    cage=cage,
                    website=sam_website if sam_api_keys else None,
                    notes="; ".join(notes),
                    item=ProviderItemCreate(
                        nsn=nsn,
                        fsc=fsc,
                        nomenclature=nomenclature,
                        relationship_type=row["relationship_type"],
                        source=source,
                        source_url=file_record.source_url or str(path),
                        confidence=95 if row["relationship_type"] == "Approved Source" else 85,
                        notes="; ".join(notes),
                    ),
                )
                existing = repo._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
                try:
                    repo.create(payload)
                    if existing:
                        result.updated += 1
                    else:
                        result.inserted += 1
                except Exception as exc:
                    db.rollback()
                    result.errors.append(f"{filename or path.name} / CAGE {cage}: {exc}")

    provider_seed = seed_vendor_leads_from_providers(db, opp, organization_id=organization_id)
    result.vendor_leads_created = provider_seed.get("created", 0)
    result.vendor_leads_updated = provider_seed.get("updated", 0)
    result.providers_matched = provider_seed.get("matched", 0)
    if provider_seed.get("created") or provider_seed.get("updated"):
        db.commit()
    return result
