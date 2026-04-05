from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from app.services.dibbs.session import dibbs_page, open_dibbs_rfq_list

DIBBS_BASE_URL = "https://www.dibbs.bsm.dla.mil"
VALID_DETAIL_HINTS = (
    "RFQNSN.ASPX",
    "RFQSOL.ASPX",
    "RFQSOLIC",
    "RFQ/RFQNSN.ASPX",
)


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_spaces(value: str | None) -> str | None:
    value = _safe(value)
    if not value:
        return None
    return re.sub(r"\s+", " ", value).strip()


def _normalize_nsn(value: str | None) -> str | None:
    value = _safe(value)
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 13:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
    return value


def _extract_nsn_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        value = qs.get("value", [None])[0]
        if value:
            return _normalize_nsn(value)
    except Exception:
        pass
    m = re.search(r"(\d{13}|\d{4}-\d{2}-\d{3}-\d{4})", url)
    if m:
        return _normalize_nsn(m.group(1))
    return None


def _is_valid_detail_href(href: str | None) -> bool:
    href = _safe(href)
    if not href:
        return False

    upper = href.upper()

    if any(hint in upper for hint in VALID_DETAIL_HINTS):
        return True

    junk = (
        "RFQDATES.ASPX",
        "DEFAULT.ASPX",
        "RFQFILEDEFS.ASPX",
        "/DOWNLOADS/RFQ/ARCHIVE/",
        ".ZIP",
        ".TXT",
        "BQOTHERS",
    )
    if any(j in upper for j in junk):
        return False

    return False


def _extract_page_from_ctx(ctx: Any) -> Page:
    if isinstance(ctx, Page):
        return ctx

    if isinstance(ctx, tuple):
        for item in reversed(ctx):
            if hasattr(item, "goto") and hasattr(item, "content"):
                return item

    if hasattr(ctx, "goto") and hasattr(ctx, "content"):
        return ctx

    raise TypeError(f"Could not extract Playwright page from dibbs_page() context: {type(ctx)!r}")


def _extract_nomenclature(html: str) -> str | None:
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    page_text = " ".join(soup.stripped_strings)

    patterns = [
        r"Nomenclature:\s*(.+?)(?:\s+AMSC:|\s+NSN:|\s{2,})",
        r"Item Name:\s*(.+?)(?:\s+AMSC:|\s+NSN:|\s{2,})",
        r"NOUN NAME:\s*(.+?)(?:\s+AMSC:|\s+NSN:|\s{2,})",
    ]
    for pat in patterns:
        m = re.search(pat, page_text, re.IGNORECASE)
        if m:
            cand = _normalize_spaces(m.group(1))
            if cand:
                return cand

    # table-style fallback
    labels = soup.find_all(string=re.compile(r"(Nomenclature|Item Name|NOUN NAME)", re.I))
    for lbl in labels:
        parent = lbl.parent
        if not parent:
            continue
        for nxt in [parent.find_next("td"), parent.find_next("span"), parent.find_next("div")]:
            if nxt:
                cand = _normalize_spaces(nxt.get_text(" ", strip=True))
                if cand and cand.lower() not in {"nomenclature", "item name", "noun name"}:
                    return cand
    return None


def _fetch_detail_fields(page: Page, detail_url: str) -> dict[str, Any]:
    try:
        page.goto(detail_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        page.wait_for_load_state("networkidle")
        html = page.content()
    except Exception:
        return {}

    detail: dict[str, Any] = {}
    detail["nsn"] = _extract_nsn_from_url(detail_url)

    nomenclature = _extract_nomenclature(html)
    if nomenclature:
        detail["nomenclature"] = nomenclature

    pdfs = re.findall(
        r"https://dibbs2\.bsm\.dla\.mil/Downloads/RFQ/[^\s\"']+\.PDF",
        html,
        flags=re.IGNORECASE,
    )
    if pdfs:
        detail["pdf_links"] = list(dict.fromkeys(pdfs))

    return detail


def pull_dibbs_by_fsc(
    fsc_raw: str | None = None,
    limit: int = 10,
    debug: bool = False,
    fsc: str | None = None,
    **kwargs,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fsc_value = _safe(fsc_raw) or _safe(fsc)
    results: List[Dict[str, Any]] = []

    diagnostics: Dict[str, Any] = {
        "request_fsc": fsc_value,
        "request_limit": limit,
        "pages_fetched": 1,
        "rows_parsed": 0,
        "mode": "adapter",
        "final_url": None,
        "page_title": None,
    }

    if not fsc_value:
        return results, diagnostics

    with dibbs_page(headless=not debug) as ctx:
        page = _extract_page_from_ctx(ctx)

        open_dibbs_rfq_list(page, fsc_value, debug=debug)

        diagnostics["final_url"] = page.url
        try:
            diagnostics["page_title"] = page.title()
        except Exception:
            diagnostics["page_title"] = None

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        seen_urls: set[str] = set()

        detail_urls: List[tuple[str, str | None]] = []
        for a in soup.find_all("a", href=True):
            href = _safe(a.get("href"))
            text = _safe(a.get_text())

            if not _is_valid_detail_href(href):
                continue

            full_url = urljoin(DIBBS_BASE_URL, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            detail_urls.append((full_url, text))
            if len(detail_urls) >= limit:
                break

        for full_url, text in detail_urls:
            detail = _fetch_detail_fields(page, full_url)
            nsn = detail.get("nsn") or _extract_nsn_from_url(full_url) or text
            nomenclature = detail.get("nomenclature")
            title = nomenclature or text or "DIBBS RFQ"
            description = title if nomenclature else (text or "DIBBS RFQ result")

            results.append(
                {
                    "source": "DIBBS",
                    "source_opportunity_id": nsn,
                    "solicitation_number": nsn or text or "DIBBS-RFQ",
                    "title": title,
                    "agency": "DLA (DIBBS)",
                    "sub_agency": None,
                    "office": None,
                    "url": full_url,
                    "detail_url": full_url,
                    "posted_at": None,
                    "due_at": None,
                    "set_aside_type": None,
                    "fsc_code": fsc_value,
                    "place_of_performance": None,
                    "description": description,
                    "status": "new",
                    "raw_payload": {"dibbs_detail": detail} if detail else None,
                }
            )

    diagnostics["rows_parsed"] = len(results)
    return results, diagnostics
