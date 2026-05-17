from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
import urllib3
from sqlalchemy.orm import Session
from playwright.sync_api import sync_playwright

from app.core.config import settings
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.services.app_settings_service import get_setting
from app.services.document_pipeline import process_opportunity_documents
from app.services.dibbs.structured_detail_parser import parse_dibbs_detail_structured
from app.services.storage import delete_reference, ensure_dir, file_exists, storage_root, store_bytes, store_text

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _safe_dirname(s: str) -> str:
    s = (s or "").strip().split("Â»")[0].strip()
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", s)
    return s or "opportunity"


def _safe_filename(s: str) -> str:
    s = (s or "").strip().split("Â»")[0].strip()
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", s)
    s = s.replace(" ", "_")
    return s or "file"


def _normalize_source_url(url: str | None) -> str:
    return (url or "").strip()


def _effective_pdf_download_base_dir(db: Session, opp: Opportunity, explicit_base_dir: str | None = None) -> str | None:
    if explicit_base_dir and str(explicit_base_dir).strip():
        return str(explicit_base_dir).strip()
    org_id = getattr(opp, "organization_id", None)
    configured = get_setting(db, "pdf_download_path", default="", organization_id=org_id) or ""
    clean = str(configured).strip()
    return clean or None


def _matching_file_records(
    db: Session,
    opportunity_id: int,
    filename: str,
    source_url: str | None = None,
) -> list[OpportunityFile]:
    normalized_filename = _safe_filename(filename)
    normalized_source_url = _normalize_source_url(source_url)
    records = db.query(OpportunityFile).filter(
        OpportunityFile.opportunity_id == opportunity_id,
    ).all()

    matches: list[OpportunityFile] = []
    for record in records:
        same_filename = _safe_filename(getattr(record, "filename", "")) == normalized_filename
        same_source_url = bool(normalized_source_url) and _normalize_source_url(getattr(record, "source_url", None)) == normalized_source_url
        if same_filename or same_source_url:
            matches.append(record)
    return matches


def _record_sort_key(record: OpportunityFile) -> tuple[int, int, int, float]:
    parsed_score = 1 if getattr(record, "parsed_metadata", None) else 0
    text_score = 1 if getattr(record, "extracted_text", None) else 0
    file_score = 1 if getattr(record, "file_path", None) and file_exists(record.file_path) else 0
    created_score = getattr(record, "created_at", datetime.min).timestamp() if getattr(record, "created_at", None) else 0.0
    return (parsed_score, text_score, file_score, created_score)


def _collapse_duplicate_file_records(
    db: Session,
    primary: OpportunityFile,
    records: list[OpportunityFile],
) -> OpportunityFile:
    for record in records:
        if record.id == primary.id:
            continue
        if not getattr(primary, "source_url", None) and getattr(record, "source_url", None):
            primary.source_url = record.source_url
        if not getattr(primary, "extracted_text", None) and getattr(record, "extracted_text", None):
            primary.extracted_text = record.extracted_text
        if not getattr(primary, "parsed_metadata", None) and getattr(record, "parsed_metadata", None):
            primary.parsed_metadata = record.parsed_metadata
        if (
            (not getattr(primary, "file_path", None) or not file_exists(primary.file_path))
            and getattr(record, "file_path", None)
            and file_exists(record.file_path)
        ):
            primary.file_path = record.file_path
        duplicate_ref = getattr(record, "file_path", None)
        if duplicate_ref and duplicate_ref != getattr(primary, "file_path", None):
            try:
                delete_reference(duplicate_ref)
            except Exception:
                pass
        db.delete(record)
    return primary


def dedupe_opportunity_file_records(db: Session, opportunity_id: int) -> int:
    records = db.query(OpportunityFile).filter(
        OpportunityFile.opportunity_id == opportunity_id,
    ).order_by(OpportunityFile.created_at.asc(), OpportunityFile.id.asc()).all()
    groups: list[list[OpportunityFile]] = []
    key_to_group: dict[str, list[OpportunityFile]] = {}

    for record in records:
        keys = []
        normalized_filename = _safe_filename(getattr(record, "filename", "") or "")
        normalized_source_url = _normalize_source_url(getattr(record, "source_url", None))
        if normalized_filename:
            keys.append(f"filename:{normalized_filename}")
        if normalized_source_url:
            keys.append(f"url:{normalized_source_url}")
        if not keys:
            continue

        group = None
        for key in keys:
            if key in key_to_group:
                group = key_to_group[key]
                break
        if group is None:
            group = [record]
            groups.append(group)
        else:
            group.append(record)
        for key in keys:
            key_to_group[key] = group

    removed = 0
    changed = False
    for group in groups:
        unique_records = list({record.id: record for record in group}.values())
        if len(unique_records) <= 1:
            continue
        primary = sorted(unique_records, key=_record_sort_key, reverse=True)[0]
        _collapse_duplicate_file_records(db, primary, unique_records)
        removed += max(0, len(unique_records) - 1)
        changed = True

    if changed:
        db.commit()
    return removed


def _compact_solicitation(s: str | None) -> str | None:
    if not s:
        return None
    s = s.split("Â»")[0].strip()
    return re.sub(r"[^A-Za-z0-9]+", "", s)


def _page_text(page) -> str:
    try:
        return (page.locator("body").inner_text(timeout=4000) or "").strip()
    except Exception:
        return ""


def _looks_like_consent_page(page) -> bool:
    txt = _page_text(page).lower()
    signals = ["consent", "agree", "supports javascript", "please click ok", "warning", "continue"]
    return sum(1 for s in signals if s in txt) >= 2


def _looks_like_solicitation_content(page, opp: Opportunity) -> bool:
    txt = _page_text(page)
    if not txt:
        return False
    sol = _compact_solicitation(opp.solicitation_number) or ""
    txt_compact = re.sub(r"[^A-Za-z0-9]+", "", txt)
    positive = ["Solicitation #", "Return By", "Issue", "Technical Documents", "NSN:", "Approved Source Data", "DIBBS RFQ"]
    return any(p.lower() in txt.lower() for p in positive) or bool(sol and sol in txt_compact)


def _looks_like_bad_snapshot_page(page) -> bool:
    url = (page.url or "").lower()
    return "chrome-error://chromewebdata/" in url or "acqdownloads" in url


def _looks_like_dibbs_maintenance_text(text: str | None) -> bool:
    sample = str(text or "").lower()
    if not sample:
        return False
    phrases = [
        "under maintenance",
        "scheduled maintenance",
        "temporarily unavailable",
        "temporarily down",
        "system maintenance",
        "service unavailable",
        "unavailable due to maintenance",
        "site maintenance",
    ]
    return any(phrase in sample for phrase in phrases)


def _decode_preview(data: bytes | None, limit: int = 2000) -> str:
    if not data:
        return ""
    try:
        return data[:limit].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _dibbs_unavailability_payload(*, message: str, detail: str | None = None, final_url: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "DIBBS",
        "reason": "maintenance",
        "retryable": True,
        "message": message,
    }
    if detail:
        payload["detail"] = detail
    if final_url:
        payload["final_url"] = final_url
    return payload


def _click_dibbs_ok_if_present(page) -> None:
    patterns = [r"^(OK|Ok|Agree|I Agree)$", r"Continue", r"Accept"]
    for _ in range(6):
        clicked = False
        for pat in patterns:
            try:
                btn = page.locator(f"text=/{pat}/i").first
                if btn and btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2500)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(700)
                    clicked = True
                    break
            except Exception:
                pass
        if not clicked:
            break


def _stabilize_dibbs_page(page, opp: Opportunity) -> None:
    for _ in range(5):
        _click_dibbs_ok_if_present(page)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            page.wait_for_timeout(700)
        except Exception:
            pass
        if _looks_like_solicitation_content(page, opp) and not _looks_like_consent_page(page):
            return
        try:
            page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(700)
        except Exception:
            pass


def _sniff_pdf_bytes(data: bytes) -> bool:
    return bool(data and data[:4] == b"%PDF")


def _content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^\";]+)"?', value, flags=re.I)
    if not match:
        return None
    return _safe_filename(unquote(match.group(1)))


def _filename_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path or ""
    filename = Path(path).name
    return _safe_filename(filename) if filename else None


def _extension_from_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return guessed or ""


def _save_downloaded_file(
    db: Session,
    opp: Opportunity,
    out_dir: Path,
    filename: str,
    source_url: str,
    data: bytes,
    file_type: str,
) -> tuple[int, str]:
    filename = _safe_filename(filename)
    matching_records = _matching_file_records(db, opp.id, filename, source_url)
    existing = None
    if matching_records:
        existing = sorted(matching_records, key=_record_sort_key, reverse=True)[0]
        existing = _collapse_duplicate_file_records(db, existing, matching_records)
    if existing is not None and file_exists(existing.file_path):
        existing.file_type = file_type
        existing.source_url = source_url or existing.source_url
        existing.filename = filename
        db.add(existing)
        db.commit()
        return 0, filename
    fp = out_dir / filename
    stored_ref = store_bytes(fp, data, content_type="application/pdf" if filename.lower().endswith(".pdf") else None)
    if existing is not None:
        existing.file_type = file_type
        existing.source_url = source_url
        existing.file_path = stored_ref
        db.add(existing)
    else:
        db.add(
            OpportunityFile(
                organization_id=getattr(opp, "organization_id", None),
                opportunity_id=opp.id,
                file_type=file_type,
                filename=filename,
                source_url=source_url,
                file_path=stored_ref,
                created_at=datetime.utcnow(),
            )
        )
    db.commit()
    return 1, filename


def _save_text_file_record(
    db: Session,
    opp: Opportunity,
    out_dir: Path,
    filename: str,
    source_url: str | None,
    text: str,
    file_type: str,
    parsed_metadata: dict[str, Any] | None = None,
) -> tuple[int, str]:
    filename = _safe_filename(filename)
    matching_records = _matching_file_records(db, opp.id, filename, source_url)
    existing = None
    if matching_records:
        existing = sorted(matching_records, key=_record_sort_key, reverse=True)[0]
        existing = _collapse_duplicate_file_records(db, existing, matching_records)
    if existing is not None and file_exists(existing.file_path):
        existing.file_type = file_type
        existing.source_url = source_url or existing.source_url
        existing.filename = filename
        existing.extracted_text = text or existing.extracted_text
        if parsed_metadata:
            existing.parsed_metadata = {**(getattr(existing, "parsed_metadata", None) or {}), **parsed_metadata}
        db.add(existing)
        db.commit()
        return 0, filename

    fp = out_dir / filename
    stored_ref = store_text(fp, text, encoding="utf-8")
    if existing is not None:
        existing.file_type = file_type
        existing.source_url = source_url
        existing.file_path = stored_ref
        existing.extracted_text = text
        if parsed_metadata:
            existing.parsed_metadata = {**(getattr(existing, "parsed_metadata", None) or {}), **parsed_metadata}
        db.add(existing)
    else:
        db.add(
            OpportunityFile(
                organization_id=getattr(opp, "organization_id", None),
                opportunity_id=opp.id,
                file_type=file_type,
                filename=filename,
                source_url=source_url,
                file_path=stored_ref,
                extracted_text=text,
                parsed_metadata=parsed_metadata or None,
                created_at=datetime.utcnow(),
            )
        )
    db.commit()
    return 1, filename


def _write_debug_log(out_dir: Path, opp: Opportunity, payload: dict) -> str:
    ensure_dir(out_dir)
    sol_clean = _safe_filename(opp.solicitation_number or f"opportunity_{opp.id}")
    path = out_dir / f"{sol_clean}_official_pdf_debug.json"
    return store_text(path, json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _create_snapshot_pdf(db: Session, opp: Opportunity, page, out_dir: Path) -> tuple[int, int, str | None]:
    sol_clean = _safe_filename(opp.solicitation_number or f"opportunity_{opp.id}")
    fname = f"{sol_clean}_fallback_snapshot.pdf"
    matching_records = _matching_file_records(db, opp.id, fname, None)
    existing = None
    if matching_records:
        existing = sorted(matching_records, key=_record_sort_key, reverse=True)[0]
        existing = _collapse_duplicate_file_records(db, existing, matching_records)
    if existing is not None and file_exists(existing.file_path):
        return 0, 1, None
    try:
        _stabilize_dibbs_page(page, opp)
        if _looks_like_consent_page(page) and not _looks_like_solicitation_content(page, opp):
            return 0, 0, "still_on_consent_page"
        if _looks_like_bad_snapshot_page(page):
            return 0, 0, "bad_snapshot_page"
        fp = out_dir / fname
        pdf_bytes = page.pdf(
            format="Letter",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0.45in", "bottom": "0.45in", "left": "0.45in", "right": "0.45in"},
        )
        stored_ref = store_bytes(fp, pdf_bytes, content_type="application/pdf")
        if existing is not None:
            existing.file_type = "PDF_FALLBACK_SNAPSHOT"
            existing.source_url = page.url
            existing.file_path = stored_ref
            db.add(existing)
        else:
            db.add(
                OpportunityFile(
                    organization_id=getattr(opp, "organization_id", None),
                    opportunity_id=opp.id,
                    file_type="PDF_FALLBACK_SNAPSHOT",
                    filename=fname,
                    source_url=page.url,
                    file_path=stored_ref,
                    created_at=datetime.utcnow(),
                )
            )
        db.commit()
        return 1, 0, None
    except Exception as exc:
        return 0, 0, str(exc)


def _cookie_dict_from_playwright(cookies: list[dict[str, Any]]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value")}


def _download_binary_via_requests(
    url: str,
    referer: str | None = None,
    cookies: list[dict[str, Any]] | None = None,
    timeout_s: int = 20,
) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if referer:
        headers["Referer"] = referer
    cookie_payload = _cookie_dict_from_playwright(cookies or [])
    cookie_payload.setdefault("DIBBSDoDWarning", "AGREE")
    try:
        try:
            response = requests.get(
                url,
                headers=headers,
                cookies=cookie_payload,
                timeout=timeout_s,
                allow_redirects=True,
            )
        except requests.exceptions.SSLError:
            response = requests.get(
                url,
                headers=headers,
                cookies=cookie_payload,
                timeout=timeout_s,
                allow_redirects=True,
                verify=False,
            )
        body = response.content or b""
        preview = _decode_preview(body)
        return {
            "ok": response.ok and bool(body),
            "bytes": body,
            "final_url": response.url,
            "content_type": response.headers.get("content-type"),
            "content_disposition": response.headers.get("content-disposition"),
            "details": {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body_len": len(body),
                "is_pdf": _sniff_pdf_bytes(body),
                "preview_text": preview,
            },
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "details": {}}


def _dedupe_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for candidate in candidates:
        url = (candidate.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(candidate)
    return unique


def _extract_urlish_candidates(value: Any, default_label: str | None = None) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://"):
            candidates.append({"url": value, "label": default_label or _filename_from_url(value) or value})
        return candidates
    if isinstance(value, dict):
        url = value.get("url") or value.get("href") or value.get("link") or value.get("resourceLink")
        if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
            label = value.get("name") or value.get("title") or value.get("label") or value.get("fileName") or default_label
            candidates.append({"url": url, "label": str(label or _filename_from_url(url) or url)})
        return candidates
    if isinstance(value, list):
        for item in value:
            candidates.extend(_extract_urlish_candidates(item, default_label=default_label))
    return candidates


def _collect_dibbs_file_candidates(opp: Opportunity, page=None) -> list[dict[str, str]]:
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    candidates: list[dict[str, str]] = []

    search_row = raw_payload.get("dibbs_search_row")
    if isinstance(search_row, dict) and search_row.get("pdf_url"):
        pdf_url = str(search_row.get("pdf_url"))
        candidates.append(
            {
                "url": pdf_url,
                "label": str(
                    search_row.get("solicitation_number")
                    or search_row.get("nsn")
                    or Path(pdf_url).name
                ),
            }
        )

    detail = raw_payload.get("dibbs_detail")
    if isinstance(detail, dict):
        structured = detail.get("structured") if isinstance(detail.get("structured"), dict) else detail
        file_links = structured.get("file_links") if isinstance(structured, dict) else []
        if isinstance(file_links, list):
            for item in file_links:
                if isinstance(item, dict) and item.get("url"):
                    candidates.append(
                        {
                            "url": str(item.get("url")),
                            "label": str(item.get("text") or item.get("url")),
                        }
                    )

        for pdf_url in detail.get("pdf_links") or []:
            if pdf_url:
                candidates.append({"url": str(pdf_url), "label": Path(str(pdf_url)).name})

    selected = raw_payload.get("dibbs_selected_solicitation") or {}
    if isinstance(selected, dict) and selected.get("pdf_url"):
        candidates.append(
            {
                "url": str(selected.get("pdf_url")),
                "label": str(selected.get("solicitation_number") or Path(str(selected.get("pdf_url"))).name),
            }
        )

    if page is not None:
        try:
            parsed = parse_dibbs_detail_structured(page.content(), page.url)
            for item in parsed.get("file_links") or []:
                if isinstance(item, dict) and item.get("url"):
                    candidates.append(
                        {
                            "url": str(item.get("url")),
                            "label": str(item.get("text") or item.get("url")),
                        }
                    )
        except Exception:
            pass

    return _dedupe_candidates(candidates)


def _should_create_fallback_snapshot(always_snapshot: bool, downloaded_files: list[dict[str, str]]) -> bool:
    return bool(always_snapshot) and not downloaded_files


def _preferred_dibbs_detail_pdf_url(opp: Opportunity) -> str | None:
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})

    search_row = raw_payload.get("dibbs_search_row") or {}
    if isinstance(search_row, dict):
        pdf_url = search_row.get("pdf_url")
        if isinstance(pdf_url, str) and pdf_url.startswith("http"):
            return pdf_url

    selected = raw_payload.get("dibbs_selected_solicitation") or {}
    if isinstance(selected, dict):
        pdf_url = selected.get("pdf_url")
        if isinstance(pdf_url, str) and pdf_url.startswith("http"):
            return pdf_url

    detail = raw_payload.get("dibbs_detail") or {}
    if isinstance(detail, dict):
        structured = detail.get("structured") if isinstance(detail.get("structured"), dict) else detail
        if isinstance(structured, dict):
            for row in structured.get("solicitations") or []:
                if not isinstance(row, dict):
                    continue
                pdf_url = row.get("pdf_url")
                if isinstance(pdf_url, str) and pdf_url.startswith("http"):
                    return pdf_url
        for pdf_url in detail.get("pdf_links") or []:
            if isinstance(pdf_url, str) and pdf_url.startswith("http"):
                return pdf_url

    sol_compact = _compact_solicitation(opp.solicitation_number) or ""
    if sol_compact and sol_compact.upper().startswith("SPE"):
        return f"https://dibbs2.bsm.dla.mil/Downloads/RFQ/{sol_compact[-1]}/{sol_compact}.PDF"
    return None


def _sam_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    bearer = getattr(settings, "SAM_BEARER_TOKEN", None)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _fetch_sam_notice_detail(opp: Opportunity) -> dict[str, Any]:
    api_key = getattr(settings, "SAM_API_KEY", None)
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    notice_id = raw_payload.get("noticeId") or raw_payload.get("id") or raw_payload.get("opportunityId")
    if not notice_id or not api_key:
        return {}
    try:
        response = requests.get(
            "https://api.sam.gov/prod/opportunities/v1/noticedesc",
            params={"noticeid": notice_id, "api_key": api_key},
            headers=_sam_headers(api_key),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _collect_sam_file_candidates(opp: Opportunity) -> list[dict[str, str]]:
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    detail_payload = _fetch_sam_notice_detail(opp)
    candidates: list[dict[str, str]] = []

    for payload in [raw_payload, detail_payload]:
        for key in ("resourceLinks", "attachments", "attachmentLinks", "fileLinks"):
            candidates.extend(_extract_urlish_candidates(payload.get(key), default_label=key))

    return _dedupe_candidates(candidates)


def _is_url_like(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith("http://") or text.startswith("https://")


def _clean_notice_text(value: Any) -> str:
    text = str(value or "")
    text = unescape(text)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_notice_body(payload: dict[str, Any]) -> str:
    def _usable_notice_text(value: str) -> str:
        cleaned = _clean_notice_text(value)
        if re.fullmatch(r"[a-f0-9]{32}", cleaned, flags=re.IGNORECASE):
            return ""
        return cleaned

    preferred_keys = (
        "descriptionText",
        "description",
        "noticeText",
        "body",
        "content",
        "html",
        "message",
    )
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and not _is_url_like(value):
            cleaned = _usable_notice_text(value)
            if cleaned:
                return cleaned

    for key, value in payload.items():
        if isinstance(value, str) and any(tok in key.lower() for tok in ("description", "notice", "body", "content")) and not _is_url_like(value):
            cleaned = _usable_notice_text(value)
            if cleaned:
                return cleaned
    return ""


def _build_sam_notice_text(opp: Opportunity, detail_payload: dict[str, Any]) -> str:
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})
    lines: list[str] = []

    def add(label: str, value: Any) -> None:
        text = _clean_notice_text(value)
        if text:
            lines.append(f"{label}: {text}")

    add("Title", getattr(opp, "title", None) or raw_payload.get("title"))
    add("Solicitation Number", getattr(opp, "solicitation_number", None) or raw_payload.get("solicitationNumber"))
    add("Agency", raw_payload.get("fullParentPathName"))
    add("Set-Aside", raw_payload.get("typeOfSetAsideDescription") or raw_payload.get("typeOfSetAside"))
    add("Response Deadline", raw_payload.get("responseDeadLine"))
    add("NAICS", raw_payload.get("naicsCode"))
    add("FSC", raw_payload.get("classificationCode"))

    place = raw_payload.get("placeOfPerformance") if isinstance(raw_payload.get("placeOfPerformance"), dict) else {}
    place_bits = [
        (((place.get("city") or {}) if isinstance(place.get("city"), dict) else {}).get("name")),
        (((place.get("state") or {}) if isinstance(place.get("state"), dict) else {}).get("name")),
        place.get("zip"),
        (((place.get("country") or {}) if isinstance(place.get("country"), dict) else {}).get("name")),
    ]
    add("Place of Performance", ", ".join(str(bit).strip() for bit in place_bits if bit))

    contacts = raw_payload.get("pointOfContact")
    if isinstance(contacts, list) and contacts:
        contact_lines: list[str] = []
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            parts = [contact.get("fullName"), contact.get("email"), contact.get("phone")]
            joined = " | ".join(str(part).strip() for part in parts if part)
            if joined:
                contact_lines.append(joined)
        if contact_lines:
            lines.append("Contacts:\n" + "\n".join(contact_lines))

    notice_text = _extract_notice_body(detail_payload) or _extract_notice_body(raw_payload)
    if notice_text:
        lines.append("Notice Description:\n" + notice_text)

    resource_links = []
    for key in ("resourceLinks", "attachments", "attachmentLinks", "fileLinks", "links"):
        for item in _extract_urlish_candidates(raw_payload.get(key), default_label=key):
            resource_links.append(f"- {item.get('label') or item.get('url')}: {item.get('url')}")
        for item in _extract_urlish_candidates(detail_payload.get(key), default_label=key):
            resource_links.append(f"- {item.get('label') or item.get('url')}: {item.get('url')}")
    if raw_payload.get("additionalInfoLink"):
        resource_links.append(f"- Additional Info: {raw_payload.get('additionalInfoLink')}")
    if raw_payload.get("uiLink"):
        resource_links.append(f"- SAM Workspace: {raw_payload.get('uiLink')}")
    if resource_links:
        lines.append("Reference Links:\n" + "\n".join(dict.fromkeys(resource_links)))

    return "\n\n".join(line for line in lines if line).strip()


def _collect_sam_file_candidates_from_page(opp: Opportunity) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(opp.url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                rows = page.eval_on_selector_all(
                    "app-attachments a[href], #attachments a[href], #links-attachments a[href], #files a[href]",
                    "els => els.map(el => ({ href: el.href, text: (el.innerText || '').trim() }))",
                )
                for row in rows:
                    href = row.get("href")
                    text = row.get("text")
                    if href:
                        candidates.append({"url": str(href), "label": str(text or href)})
            finally:
                browser.close()
    except Exception:
        return []
    return _dedupe_candidates(candidates)


def _looks_like_downloadable_file(url: str, content_type: str | None) -> bool:
    path = (urlparse(url).path or "").lower()
    if any(
        path.endswith(ext)
        for ext in (
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".zip",
            ".txt",
            ".csv",
            ".xml",
            ".json",
            ".rtf",
        )
    ):
        return True
    content_type = (content_type or "").lower()
    if not content_type:
        return False
    if content_type.startswith("text/html"):
        return False
    return True


def download_pdfs_for_opportunity(
    db: Session,
    opportunity_id: int,
    base_dir: str | None = None,
    always_snapshot: bool = True,
    prefer_dibbs_solicitation_detail: bool = True,
) -> dict[str, Any]:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ValueError("Opportunity not found")
    dedupe_opportunity_file_records(db, opportunity_id)

    sol = opp.solicitation_number or f"opportunity_{opp.id}"
    sol_compact = _compact_solicitation(opp.solicitation_number) or ""
    folder = _safe_dirname(sol)
    out_dir = ensure_dir(storage_root(_effective_pdf_download_base_dir(db, opp, base_dir)) / folder / "documents")

    created = 0
    skipped = 0
    errors: list[str] = []
    official_pdf_saved = False
    official_pdf_filename = None
    official_pdf_error = None
    source_unavailable = None
    debug_log_path = None
    downloaded_files: list[dict[str, str]] = []
    detail_url = None
    snapshot = None
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})

    if (opp.source or "").upper() == "SAM":
        detail_payload = _fetch_sam_notice_detail(opp)
        sam_candidates = _collect_sam_file_candidates(opp)
        if not sam_candidates:
            official_pdf_error = "no_sam_attachments_found"
            errors.append("SAM opportunity did not expose any attachment/resource links.")
        for candidate in sam_candidates:
            result = _download_binary_via_requests(candidate["url"], referer=opp.url)
            if not result.get("ok"):
                errors.append(f"{candidate['url']} -> {result.get('reason', 'download_failed')}")
                continue
            final_url = result.get("final_url") or candidate["url"]
            if not _looks_like_downloadable_file(final_url, result.get("content_type")):
                errors.append(f"{candidate['url']} -> not_a_downloadable_file")
                continue

            filename = (
                _content_disposition_filename(result.get("content_disposition"))
                or candidate.get("label")
                or _filename_from_url(final_url)
                or "sam_attachment"
            )
            if "." not in filename:
                ext = _extension_from_content_type(result.get("content_type"))
                if ext:
                    filename = f"{filename}{ext}"

            created_now, saved_name = _save_downloaded_file(
                db,
                opp,
                out_dir,
                filename,
                final_url,
                result["bytes"],
                "SAM_ATTACHMENT",
            )
            created += created_now
            if created_now == 0:
                skipped += 1
            downloaded_files.append(
                {
                    "filename": saved_name,
                    "source_url": final_url,
                    "file_type": "SAM_ATTACHMENT",
                }
            )

        notice_text = _build_sam_notice_text(opp, detail_payload)
        if notice_text:
            notice_filename = f"{_safe_filename(sol)}_sam_notice.txt"
            created_now, saved_name = _save_text_file_record(
                db,
                opp,
                out_dir,
                notice_filename,
                raw_payload.get("uiLink") or opp.url,
                notice_text,
                "SAM_NOTICE",
                parsed_metadata={
                    "source_basis": "sam_notice_detail",
                    "document_type": "SOLICITATION",
                    "notice_id": raw_payload.get("noticeId"),
                },
            )
            created += created_now
            if created_now == 0:
                skipped += 1
            downloaded_files.append(
                {
                    "filename": saved_name,
                    "source_url": raw_payload.get("uiLink") or opp.url,
                    "file_type": "SAM_NOTICE",
                }
            )
        elif not downloaded_files:
            errors.append("SAM notice text could not be built from notice detail or raw payload.")
    else:
        detail_url = _preferred_dibbs_detail_pdf_url(opp) if prefer_dibbs_solicitation_detail else None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            page.goto(opp.url, wait_until="domcontentloaded", timeout=60000)
            _stabilize_dibbs_page(page, opp)

            try:
                cookies = context.cookies(["https://www.dibbs.bsm.dla.mil", "https://dibbs2.bsm.dla.mil"])
            except Exception:
                cookies = []

            dibbs_candidates = _collect_dibbs_file_candidates(opp, page=page)
            if detail_url:
                dibbs_candidates = _dedupe_candidates(
                    [{"url": detail_url, "label": Path(detail_url).name}] + dibbs_candidates
                )

            debug_payload: dict[str, Any] = {
                "start_url": opp.url,
                "page_url": page.url,
                "solicitation_number": opp.solicitation_number,
                "detail_url": detail_url,
                "dibbs_candidates": dibbs_candidates,
            }

            for candidate in dibbs_candidates:
                result = _download_binary_via_requests(candidate["url"], referer=opp.url, cookies=cookies)
                if not result.get("ok"):
                    errors.append(f"{candidate['url']} -> {result.get('reason', 'download_failed')}")
                    continue
                if not _sniff_pdf_bytes(result["bytes"]):
                    preview_text = (((result.get("details") or {}).get("preview_text")) or "")
                    if _looks_like_dibbs_maintenance_text(preview_text):
                        source_unavailable = _dibbs_unavailability_payload(
                            message="DIBBS is temporarily unavailable due to maintenance. We saved the fallback snapshot and you can retry the official PDF later.",
                            detail="official_pdf_returned_maintenance_page",
                            final_url=result.get("final_url") or candidate["url"],
                        )
                        official_pdf_error = "dibbs_maintenance"
                    errors.append(f"{candidate['url']} -> not_a_pdf")
                    continue

                filename = (
                    _content_disposition_filename(result.get("content_disposition"))
                    or candidate.get("label")
                    or _filename_from_url(result.get("final_url") or candidate["url"])
                    or f"{sol_compact or opp.id}.pdf"
                )
                if not filename.lower().endswith(".pdf"):
                    filename = f"{filename}.pdf"

                created_now, saved_name = _save_downloaded_file(
                    db,
                    opp,
                    out_dir,
                    filename,
                    result.get("final_url") or candidate["url"],
                    result["bytes"],
                    "DIBBS_ATTACHMENT",
                )
                created += created_now
                if created_now == 0:
                    skipped += 1
                else:
                    official_pdf_saved = True
                    official_pdf_filename = saved_name

                downloaded_files.append(
                    {
                        "filename": saved_name,
                        "source_url": result.get("final_url") or candidate["url"],
                        "file_type": "DIBBS_ATTACHMENT",
                    }
                )

            if not downloaded_files:
                official_pdf_error = official_pdf_error or "no_dibbs_pdfs_downloaded"

            try:
                debug_log_path = _write_debug_log(out_dir, opp, debug_payload)
            except Exception as exc:
                errors.append(f"debug_log_write_failed -> {exc}")

            if _should_create_fallback_snapshot(always_snapshot, downloaded_files):
                c, s, e = _create_snapshot_pdf(db, opp, page, out_dir)
                created += c
                skipped += s
                snapshot = {"created": c, "skipped": s, "error": e, "url": page.url}
                if source_unavailable is None and _looks_like_dibbs_maintenance_text(_page_text(page)):
                    source_unavailable = _dibbs_unavailability_payload(
                        message="DIBBS is temporarily unavailable due to maintenance. We kept the workspace snapshot and existing extracted data.",
                        detail="snapshot_page_detected_maintenance",
                        final_url=page.url,
                    )
                    official_pdf_error = "dibbs_maintenance"
            elif always_snapshot:
                snapshot = {
                    "created": 0,
                    "skipped": 1,
                    "error": "official_pdf_already_downloaded",
                    "url": page.url,
                }

            context.close()
            browser.close()

    result = {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "start_url": opp.url,
        "detail_url": detail_url,
        "official_pdf_saved": official_pdf_saved,
        "official_pdf_filename": official_pdf_filename,
        "official_pdf_error": official_pdf_error,
        "source_unavailable": source_unavailable,
        "debug_log_path": debug_log_path,
        "snapshot": snapshot if always_snapshot else None,
        "downloaded_files": downloaded_files,
        "folder": str(out_dir),
    }
    try:
        result["processing"] = process_opportunity_documents(db, opp.id, force=False)
    except Exception as exc:
        result["processing_error"] = str(exc)
    try:
        from app.services.providers.pdf_cage_extractor import extract_providers_from_opportunity_pdfs

        result["provider_vendor_sync"] = extract_providers_from_opportunity_pdfs(
            db,
            opp,
            enrich_with_sam=True,
            organization_id=getattr(opp, "organization_id", None),
        ).model_dump()
    except Exception as exc:
        result["provider_vendor_sync_error"] = str(exc)
    try:
        from app.services.pricing_intelligence import extract_price_history_for_opportunity

        result["pricing_intelligence"] = extract_price_history_for_opportunity(db, opp)
    except Exception as exc:
        result["pricing_intelligence_error"] = str(exc)
    return result
