from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(text: str | None) -> str | None:
    text = _safe(text)
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()


def _extract_nsn(blob: str | None) -> str | None:
    if not blob:
        return None
    m = re.search(r"\b(\d{13})\b", blob)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{4}-\d{2}-\d{3,})\b", blob)
    if m:
        return m.group(1)
    return None


def _extract_fsc(blob: str | None) -> str | None:
    if not blob:
        return None
    m = re.search(r"\bFSC\b[:\s\-]*([0-9]{4})\b", blob, flags=re.I)
    if m:
        return m.group(1)
    return None


def _extract_part_numbers(blob: str | None) -> list[str]:
    if not blob:
        return []
    patterns = [
        r"\bP/N\b[:\s\-]*([A-Z0-9\-\/\.]+)",
        r"\bPART NUMBER\b[:\s\-]*([A-Z0-9\-\/\.]+)",
        r"\bMFG(?:\.| )?PART\b[:\s\-]*([A-Z0-9\-\/\.]+)",
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, blob, flags=re.I):
            val = _norm(m.group(1))
            if val and val not in found:
                found.append(val)
    return found[:15]


def _extract_manufacturers(blob: str | None) -> list[str]:
    if not blob:
        return []
    patterns = [
        r"\bMANUFACTURER\b[:\s\-]*([A-Z0-9 ,\.\-&/]+)",
        r"\bMFG NAME\b[:\s\-]*([A-Z0-9 ,\.\-&/]+)",
        r"\bBRAND NAME\b[:\s\-]*([A-Z0-9 ,\.\-&/]+)",
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, blob, flags=re.I):
            val = _norm(m.group(1))
            if val and len(val) > 2 and val not in found:
                found.append(val)
    return found[:10]


def _extract_approved_sources(blob: str | None) -> list[str]:
    if not blob:
        return []
    found = []
    for m in re.finditer(r"\b([A-Z0-9]{5})\b", blob):
        token = m.group(1)
        if token not in found:
            found.append(token)
    return found[:25]


def _collect_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        text = _norm(a.get_text(" ", strip=True)) or ""
        key = (href, text)
        if key in seen:
            continue
        seen.add(key)
        if any(tok in href.lower() for tok in [".pdf", "download", "attachment", "file"]) or "pdf" in text.lower():
            links.append({"text": text, "url": href})
    return links[:50]


def _parse_detail_html(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = _norm(soup.get_text(" ", strip=True)) or ""

    title = None
    h1 = soup.find(["h1", "h2", "title"])
    if h1:
        title = _norm(h1.get_text(" ", strip=True))

    nsn = _extract_nsn(page_text) or _extract_nsn(url)
    fsc = _extract_fsc(page_text)
    part_numbers = _extract_part_numbers(page_text)
    manufacturers = _extract_manufacturers(page_text)
    approved_sources = _extract_approved_sources(page_text)
    file_links = _collect_links(soup, url)

    return {
        "detail_title": title,
        "nsn": nsn,
        "fsc_code": fsc,
        "part_numbers": part_numbers,
        "manufacturers": manufacturers,
        "approved_sources": approved_sources,
        "file_links": file_links,
        "page_excerpt": page_text[:4000],
    }


def enrich_dibbs_opportunity(db: Session, opportunity: Opportunity) -> dict[str, Any]:
    url = _safe(getattr(opportunity, "url", None))
    if not url:
        return {"ok": False, "error": "Opportunity has no URL"}

    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()

    parsed = _parse_detail_html(resp.text, url)

    raw_payload = dict(getattr(opportunity, "raw_payload", None) or {})
    raw_payload["dibbs_detail"] = parsed

    if not getattr(opportunity, "description", None):
        desc_parts = []
        if parsed.get("nsn"):
            desc_parts.append(f"NSN: {parsed['nsn']}")
        if parsed.get("fsc_code"):
            desc_parts.append(f"FSC: {parsed['fsc_code']}")
        if parsed.get("part_numbers"):
            desc_parts.append(f"Part Numbers: {', '.join(parsed['part_numbers'][:5])}")
        if parsed.get("manufacturers"):
            desc_parts.append(f"Manufacturers: {', '.join(parsed['manufacturers'][:5])}")
        if desc_parts:
            opportunity.description = " | ".join(desc_parts)

    if not getattr(opportunity, "fsc_code", None) and parsed.get("fsc_code"):
        opportunity.fsc_code = parsed["fsc_code"]

    opportunity.raw_payload = raw_payload
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)

    return {
        "ok": True,
        "opportunity_id": opportunity.id,
        "url": url,
        "enriched_fields": {
            "fsc_code": opportunity.fsc_code,
            "description": opportunity.description,
            "raw_payload_keys": list(raw_payload.keys()),
        },
        "parsed": parsed,
    }


def enrich_dibbs_batch(db: Session, limit: int = 10, source: str = "DIBBS") -> dict[str, Any]:
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

    for opp in rows:
        try:
            out = enrich_dibbs_opportunity(db, opp)
            results.append(out)
            if out.get("ok"):
                enriched += 1
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
        "results": results,
    }
