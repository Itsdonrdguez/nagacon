from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.workspace import WorkspaceArtifact
from app.services.nsn_catalog.normalizer import compact_nsn, normalize_nsn
from app.services.workspace_service import create_artifact

WBPARTS_ARTIFACT_TYPE = "WBPARTS_REFERENCE"
WBPARTS_BASE_URL = "https://www.wbparts.com/rfq/{nsn}.html"


def get_wbparts_reference(
    db: Session,
    nsn: str,
    *,
    opportunity_id: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    parsed = normalize_nsn(nsn)
    if not parsed:
        return {"status": "invalid_nsn", "input": nsn, "cross_references": [], "part_alternates": []}

    if not bool(getattr(settings, "WBPARTS_ENABLED", True)):
        return {
            "status": "disabled",
            "nsn": parsed.nsn,
            "compact_nsn": parsed.compact,
            "source_url": WBPARTS_BASE_URL.format(nsn=parsed.nsn),
            "cross_references": [],
            "part_alternates": [],
        }

    if opportunity_id and not force_refresh:
        cached = _load_cached_reference(db, opportunity_id=opportunity_id, compact_nsn=parsed.compact)
        if cached:
            return cached

    result = _fetch_and_parse(parsed.nsn)
    result.setdefault("nsn", parsed.nsn)
    result.setdefault("compact_nsn", parsed.compact)
    result.setdefault("source_url", WBPARTS_BASE_URL.format(nsn=parsed.nsn))

    if opportunity_id:
        _persist_cached_reference(db, opportunity_id=opportunity_id, result=result)
    return result


def _load_cached_reference(db: Session, *, opportunity_id: int, compact_nsn: str) -> dict[str, Any] | None:
    artifact = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opportunity_id,
            WorkspaceArtifact.artifact_type == WBPARTS_ARTIFACT_TYPE,
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    if not artifact or not isinstance(artifact.content_json, dict):
        return None
    payload = dict(artifact.content_json.get("wbparts") or {})
    if str(payload.get("compact_nsn") or "").strip() != compact_nsn:
        return None
    fetched_at = _parse_dt(payload.get("fetched_at"))
    cache_days = int(getattr(settings, "WBPARTS_CACHE_DAYS", 14) or 14)
    if fetched_at and fetched_at >= datetime.utcnow() - timedelta(days=max(cache_days, 1)):
        payload["cache_hit"] = True
        payload["artifact_id"] = artifact.id
        return payload
    return None


def _persist_cached_reference(db: Session, *, opportunity_id: int, result: dict[str, Any]) -> None:
    title = f"WBParts Reference - {result.get('nsn') or opportunity_id}"
    create_artifact(
        db,
        opportunity_id,
        WBPARTS_ARTIFACT_TYPE,
        title,
        content_json={
            "wbparts": {
                **_json_safe(result),
                "cached_at": datetime.utcnow().isoformat(),
            }
        },
        replace_existing=True,
    )


def _fetch_and_parse(nsn: str) -> dict[str, Any]:
    url_candidates = _candidate_urls(nsn)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NagaCon/1.0; +https://local.nagacon)",
        "Accept": "text/html,application/xhtml+xml",
    }
    timeout = float(getattr(settings, "WBPARTS_TIMEOUT_SECONDS", 20) or 20)
    last_error: dict[str, Any] | None = None
    for url in url_candidates:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 404:
                last_error = {
                    "status": "not_found",
                    "nsn": nsn,
                    "source_url": url,
                    "fetched_at": datetime.utcnow().isoformat(),
                    "cross_references": [],
                    "part_alternates": [],
                }
                continue
            response.raise_for_status()
            parsed = _parse_wbparts_html(response.text, nsn=nsn, source_url=url)
            parsed["attempted_urls"] = url_candidates
            return parsed
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            last_error = {
                "status": "error",
                "nsn": nsn,
                "source_url": url,
                "fetched_at": datetime.utcnow().isoformat(),
                "error": f"{exc.__class__.__name__}: {str(exc)[:300]}",
                "error_status": status_code,
                "cross_references": [],
                "part_alternates": [],
                "attempted_urls": url_candidates,
            }
            if status_code not in {404, 429}:
                return last_error
    return last_error or {
        "status": "not_found",
        "nsn": nsn,
        "source_url": url_candidates[0],
        "fetched_at": datetime.utcnow().isoformat(),
        "cross_references": [],
        "part_alternates": [],
        "attempted_urls": url_candidates,
    }


def _parse_wbparts_html(html: str, *, nsn: str, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    page_text = soup.get_text("\n", strip=True)
    title = _first_text(soup, ["h1"])
    product_heading = _find_heading_text(soup, "Product Details")
    item_name = None
    if product_heading and "|" in product_heading:
        item_name = product_heading.split("|", 1)[1].strip() or None

    part_alternates = _parse_part_alternates(page_text, nsn=nsn)
    cross_reference_rows = _parse_table_after_heading(soup, "Cross Reference")
    if not cross_reference_rows:
        cross_reference_rows = _parse_cross_reference_blocks(soup)
    demand_history_rows = _parse_table_after_heading(soup, "Demand History")
    related_products = _parse_related_products(soup)

    return {
        "status": "ok",
        "nsn": nsn,
        "source_url": source_url,
        "fetched_at": datetime.utcnow().isoformat(),
        "title": _clean(title, 240),
        "item_name": _clean(item_name, 240),
        "part_alternates": part_alternates,
        "cross_references": _normalize_cross_references(cross_reference_rows, nsn=nsn),
        "related_products": related_products,
        "demand_history": _normalize_demand_history(demand_history_rows, nsn=nsn),
        "summary": {
            "alternate_count": len(part_alternates),
            "cross_reference_count": len(cross_reference_rows),
            "related_product_count": len(related_products),
            "demand_history_count": len(demand_history_rows),
        },
    }


def _parse_part_alternates(text: str, *, nsn: str | None = None) -> list[str]:
    match = re.search(r"Part Alternates:\s*(.+)", text, re.IGNORECASE)
    if not match:
        return []
    line = match.group(1).strip()
    line = re.split(r"\n|Supply Group \(FSG\)|Demand History|Cross Reference|Technical Data|Related Products", line, maxsplit=1)[0]
    values = [_clean(item, 80) for item in line.split(",")]
    return [item for item in _unique(values) if item and not _is_nsn_like_part_number(item, nsn=nsn)]


def _parse_related_products(soup: BeautifulSoup) -> list[str]:
    heading = _find_heading_node(soup, "Related Products")
    if not heading:
        return []
    current = heading.next_sibling
    while current:
        if isinstance(current, Tag):
            text = current.get_text(" ", strip=True)
            if text:
                values = re.split(r"\s*,\s*", text)
                clean = [item for item in (_clean(value, 40) for value in values) if item and re.search(r"\d{4}-\d{2}-\d{3}-\d{4}|\d{13}", item)]
                if clean:
                    return _unique(clean)
        current = getattr(current, "next_sibling", None)
    return []


def _parse_table_after_heading(soup: BeautifulSoup, heading_text: str) -> list[dict[str, str]]:
    heading = _find_heading_node(soup, heading_text)
    if not heading:
        return []
    table = heading.find_next("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [_clean(cell.get_text(" ", strip=True), 80) or "" for cell in rows[0].find_all(["th", "td"])]
    output: list[dict[str, str]] = []
    for row in rows[1:]:
        cells = [_clean(cell.get_text(" ", strip=True), 240) or "" for cell in row.find_all(["th", "td"])]
        if not any(cells):
            continue
        item = {headers[index] or f"column_{index}": cells[index] if index < len(cells) else "" for index in range(len(headers))}
        output.append(item)
    return output


def _normalize_cross_references(rows: list[dict[str, str]], *, nsn: str | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        part_number = _clean(row.get("Part Number") or row.get("Reference Number"), 120)
        if not part_number:
            fallback_part = _clean(row.get("NSN Number"), 120)
            if fallback_part and not _is_nsn_like_part_number(fallback_part, nsn=nsn):
                part_number = fallback_part
        if _is_nsn_like_part_number(part_number, nsn=nsn):
            part_number = None
        cage = _normalize_cage(row.get("Cage Code"))
        manufacturer = _clean(row.get("Manufacturer") or row.get("Company Name"), 240)
        if not part_number and not cage and not manufacturer:
            continue
        dedupe_key = ((part_number or "").upper(), (cage or "").upper(), (manufacturer or "").upper())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        confidence = 55
        if part_number:
            confidence += 5
        if cage:
            confidence += 7
        if manufacturer:
            confidence += 6
        normalized.append(
            {
                "part_number": part_number,
                "cage": cage,
                "manufacturer": manufacturer,
                "source": "WBParts",
                "relationship_type": "Cross Reference",
                "confidence": min(confidence, 78),
            }
        )
    return normalized


def _normalize_demand_history(rows: list[dict[str, str]], *, nsn: str | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        part_number = _clean(row.get("Part Number"), 120)
        if _is_nsn_like_part_number(part_number, nsn=nsn):
            part_number = None
        request_date = _clean(row.get("Request Date"), 40)
        qty = _clean(row.get("QTY"), 40)
        origin = _clean(row.get("Origin"), 80)
        if not part_number and not request_date and not qty and not origin:
            continue
        normalized.append(
            {
                "part_number": part_number,
                "request_date": request_date,
                "quantity": qty,
                "origin": origin,
            }
        )
    return normalized


def _find_heading_node(soup: BeautifulSoup, value: str) -> Tag | None:
    needle = value.lower()
    for node in soup.find_all(re.compile("^h[1-6]$")):
        text = node.get_text(" ", strip=True)
        if needle in text.lower():
            return node
    return None


def _parse_cross_reference_blocks(soup: BeautifulSoup) -> list[dict[str, str]]:
    text = soup.get_text("\n", strip=True)
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"Part Number[:\s]+(?P<part>[A-Z0-9./_-]{2,120}).{0,120}?Cage Code[:\s]+(?P<cage>[0-9A-Z]{5}).{0,200}?Manufacturer[:\s]+(?P<manufacturer>[A-Z0-9 .,&'()/\-]{2,240})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        rows.append(
            {
                "Part Number": _clean(match.group("part"), 120) or "",
                "Cage Code": _clean(match.group("cage"), 10) or "",
                "Manufacturer": _clean(match.group("manufacturer"), 240) or "",
            }
        )
    return rows


def _find_heading_text(soup: BeautifulSoup, value: str) -> str | None:
    node = _find_heading_node(soup, value)
    return _clean(node.get_text(" ", strip=True), 240) if node else None


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return _clean(node.get_text(" ", strip=True), 240)
    return None


def _normalize_cage(value: str | None) -> str | None:
    text = _clean(value, 20)
    if not text:
        return None
    text = text.upper()
    return text if re.fullmatch(r"[0-9A-Z]{5}", text) else None


def _is_nsn_like_part_number(value: str | None, *, nsn: str | None = None) -> bool:
    text = _clean(value, 120)
    if not text:
        return False
    compact = compact_nsn(text)
    if len(compact) != 13:
        return False
    if nsn:
        return compact == compact_nsn(nsn)
    return bool(normalize_nsn(text))


def _clean(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return None
    return text[:max_len] if max_len else text


def _unique(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _candidate_urls(nsn: str) -> list[str]:
    compact = re.sub(r"\D", "", nsn)
    return [
        f"https://www.wbparts.com/rfq/{nsn}",
        f"https://www.wbparts.com/rfq/{nsn}.html",
        f"https://www.wbparts.com/rfq/{compact}",
        f"https://www.wbparts.com/rfq/{compact}.html",
    ]
