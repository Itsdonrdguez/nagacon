from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime
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
from app.services.document_pipeline import process_opportunity_documents
from app.services.dibbs.structured_detail_parser import parse_dibbs_detail_structured

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


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _already_downloaded(db: Session, opportunity_id: int, filename: str) -> bool:
    return db.query(OpportunityFile).filter(
        OpportunityFile.opportunity_id == opportunity_id,
        OpportunityFile.filename == filename,
    ).first() is not None


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
    if _already_downloaded(db, opp.id, filename):
        return 0, filename
    fp = out_dir / filename
    fp.write_bytes(data)
    db.add(
        OpportunityFile(
            organization_id=getattr(opp, "organization_id", None),
            opportunity_id=opp.id,
            file_type=file_type,
            filename=filename,
            source_url=source_url,
            file_path=str(fp.resolve()),
            created_at=datetime.utcnow(),
        )
    )
    db.commit()
    return 1, filename


def _write_debug_log(out_dir: Path, opp: Opportunity, payload: dict) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    sol_clean = _safe_filename(opp.solicitation_number or f"opportunity_{opp.id}")
    path = out_dir / f"{sol_clean}_official_pdf_debug.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(path.resolve())


def _create_snapshot_pdf(db: Session, opp: Opportunity, page, out_dir: Path) -> tuple[int, int, str | None]:
    sol_clean = _safe_filename(opp.solicitation_number or f"opportunity_{opp.id}")
    fname = f"{sol_clean}_fallback_snapshot.pdf"
    if _already_downloaded(db, opp.id, fname):
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
        fp.write_bytes(pdf_bytes)
        db.add(
            OpportunityFile(
                organization_id=getattr(opp, "organization_id", None),
                opportunity_id=opp.id,
                file_type="PDF_FALLBACK_SNAPSHOT",
                filename=fname,
                source_url=page.url,
                file_path=str(fp.resolve()),
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
    try:
        try:
            response = requests.get(
                url,
                headers=headers,
                cookies=_cookie_dict_from_playwright(cookies or []),
                timeout=timeout_s,
                allow_redirects=True,
            )
        except requests.exceptions.SSLError:
            response = requests.get(
                url,
                headers=headers,
                cookies=_cookie_dict_from_playwright(cookies or []),
                timeout=timeout_s,
                allow_redirects=True,
                verify=False,
            )
        body = response.content or b""
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


def _preferred_dibbs_detail_pdf_url(opp: Opportunity) -> str | None:
    raw_payload = dict(getattr(opp, "raw_payload", None) or {})

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


def _collect_sam_file_candidates_from_page(opp: Opportunity) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
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

    sol = opp.solicitation_number or f"opportunity_{opp.id}"
    sol_compact = _compact_solicitation(opp.solicitation_number) or ""
    folder = _safe_dirname(sol)
    if base_dir is None:
        base_dir = str(Path.cwd() / "exports")
    out_dir = _ensure_dir(Path(base_dir) / folder / "documents")

    created = 0
    skipped = 0
    errors: list[str] = []
    official_pdf_saved = False
    official_pdf_filename = None
    official_pdf_error = None
    debug_log_path = None
    downloaded_files: list[dict[str, str]] = []
    detail_url = None
    snapshot = None

    if (opp.source or "").upper() == "SAM":
        sam_candidates = _dedupe_candidates(
            _collect_sam_file_candidates(opp) + _collect_sam_file_candidates_from_page(opp)
        )
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
                result = _download_binary_via_requests(candidate["url"], referer=page.url, cookies=cookies)
                if not result.get("ok"):
                    errors.append(f"{candidate['url']} -> {result.get('reason', 'download_failed')}")
                    continue
                if not _sniff_pdf_bytes(result["bytes"]):
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
                official_pdf_error = "no_dibbs_pdfs_downloaded"

            try:
                debug_log_path = _write_debug_log(out_dir, opp, debug_payload)
            except Exception as exc:
                errors.append(f"debug_log_write_failed -> {exc}")

            if always_snapshot:
                c, s, e = _create_snapshot_pdf(db, opp, page, out_dir)
                created += c
                skipped += s
                snapshot = {"created": c, "skipped": s, "error": e, "url": page.url}

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
