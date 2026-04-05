from __future__ import annotations

# State / local scraper scaffold.
# Validate selectors, pagination, and any anti-bot behavior locally for each source
# before treating these as production-ready.

import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.schemas.opportunity import RawOpportunity
from app.services.opportunities.normalize import safe_parse_datetime

logger = logging.getLogger(__name__)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
def fetch_page(url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> str:
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    response = requests.get(url, params=params or {}, headers=merged_headers, timeout=20)
    response.raise_for_status()
    return response.text


def _pick_table(soup: BeautifulSoup):
    selectors = [
        {"id": "results"},
        {"id": "bid-results"},
        {"id": "solicitation-results"},
        {"class": "opps-table"},
        {"class": "results"},
        {"class": "gridview"},
    ]
    for attrs in selectors:
        table = soup.find("table", attrs=attrs)
        if table:
            return table
    return soup.find("table")


def _header_map(table) -> Dict[str, int]:
    header_map: Dict[str, int] = {}
    header_row = table.find("tr")
    if not header_row:
        return header_map

    headers = [th.get_text(" ", strip=True).lower() for th in header_row.find_all(["th", "td"])]
    for idx, name in enumerate(headers):
        header_map[name] = idx
    return header_map


def _cell_text(cells, idx: int) -> str:
    return cells[idx].get_text(" ", strip=True) if idx < len(cells) else ""


def _find_idx(header_map: Dict[str, int], candidates: List[str], fallback: int) -> int:
    for c in candidates:
        if c in header_map:
            return header_map[c]
    return fallback


def parse_generic_page(html: str, source: str, base_url: str) -> List[RawOpportunity]:
    soup = BeautifulSoup(html, "html.parser")
    table = _pick_table(soup)
    if not table:
        logger.warning("No table found for source=%s", source)
        return []

    header_map = _header_map(table)
    rows = table.find_all("tr")[1:] if table.find_all("tr") else []

    raw_opps: List[RawOpportunity] = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        idx_source_id = _find_idx(header_map, ["id", "opportunity id", "number"], 0)
        idx_sol = _find_idx(header_map, ["solicitation", "solicitation number", "bid number", "rfp"], 1)
        idx_title = _find_idx(header_map, ["title", "description", "summary"], 2)
        idx_agency = _find_idx(header_map, ["agency", "department", "buyer"], 3)
        idx_posted = _find_idx(header_map, ["posted", "posted date", "issue date", "release date"], 4)
        idx_due = _find_idx(header_map, ["due", "due date", "close date", "response date"], 5)
        idx_naics = _find_idx(header_map, ["naics", "naics code"], 6)
        idx_desc = _find_idx(header_map, ["details", "long description", "description"], 7)

        source_id = _cell_text(cells, idx_source_id) or _cell_text(cells, idx_sol)
        solicitation_number = _cell_text(cells, idx_sol) or source_id
        title = _cell_text(cells, idx_title)
        agency = _cell_text(cells, idx_agency)
        posted_at = safe_parse_datetime(_cell_text(cells, idx_posted))
        due_at = safe_parse_datetime(_cell_text(cells, idx_due))
        naics_code = _cell_text(cells, idx_naics) or None
        description = _cell_text(cells, idx_desc) or None

        link = row.find("a", href=True)
        url = urljoin(base_url, link["href"]) if link else None

        raw_opps.append(
            RawOpportunity(
                source=source,
                source_opportunity_id=source_id or None,
                solicitation_number=solicitation_number or None,
                title=title or None,
                agency=agency or None,
                posted_at=posted_at,
                due_at=due_at,
                naics_code=naics_code,
                description=description,
                url=url,
                raw_payload={"html_row": str(row)},
            )
        )

    return raw_opps


def fetch_eva_opportunities(params: Optional[Dict] = None, max_pages: int = 2) -> List[RawOpportunity]:
    base_url = "https://eva.virginia.gov/pages/public-search-solicitations.htm"
    params = params or {}
    all_opps: List[RawOpportunity] = []

    for page in range(1, max_pages + 1):
        html = fetch_page(base_url, params={**params, "page": page})
        opps = parse_generic_page(html, "eva", base_url)
        if not opps:
            break
        all_opps.extend(opps)

    return all_opps


def fetch_maryland_opportunities(params: Optional[Dict] = None, max_pages: int = 2) -> List[RawOpportunity]:
    base_url = "https://emma.maryland.gov/page.aspx/en/rfp/request_browse_public"
    params = params or {}
    all_opps: List[RawOpportunity] = []

    for page in range(1, max_pages + 1):
        html = fetch_page(base_url, params={**params, "page": page})
        opps = parse_generic_page(html, "maryland", base_url)
        if not opps:
            break
        all_opps.extend(opps)

    return all_opps


def fetch_dc_opportunities(params: Optional[Dict] = None, max_pages: int = 2) -> List[RawOpportunity]:
    base_url = "https://ocp.dc.gov/page/current-solicitations"
    params = params or {}
    all_opps: List[RawOpportunity] = []

    for page in range(1, max_pages + 1):
        html = fetch_page(base_url, params={**params, "page": page})
        opps = parse_generic_page(html, "dc", base_url)
        if not opps:
            break
        all_opps.extend(opps)

    return all_opps
