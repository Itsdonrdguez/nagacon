from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

DIBBS_BASE_URL = "https://www.dibbs.bsm.dla.mil"
DIBBS_RFQ_URL = "https://www.dibbs.bsm.dla.mil/RFQ/"


@dataclass
class DibbsCustomQueryResult:
    nsn: str | None
    nomenclature: str | None
    technical_documents: str | None
    solicitation_number: str | None
    pdf_url: str | None
    package_url: str | None
    status: str | None
    pr_number: str | None
    quantity: str | None
    issue_date: str | None
    return_by_date: str | None
    detail_url: str | None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.replace("\xa0", " ").replace("ť", "").strip()
    value = re.sub(r"\s+", " ", value)
    return value or None


def _clean_status(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    value = re.sub(r"\bq?uote\b", "", value, flags=re.I)
    value = _clean(value)
    return value


def _goto_with_retry(page: Page, url: str, attempts: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                page.wait_for_timeout(1500 * (attempt + 1))
    if last_error:
        raise last_error


def _accept_warning_if_needed(page: Page) -> None:
    if page.locator("#butAgree").count() > 0:
        page.locator("#butAgree").click()
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)


def _submit_fsc_custom_query(page: Page, fsc: str) -> None:
    page.select_option("#ctl00_cph1_ddlCategory", "fsc")
    page.fill("#ctl00_cph1_txtValue", str(fsc).strip())
    page.click("#ctl00_cph1_butDbGo")
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)


def _row_links(row) -> list[dict[str, str | None]]:
    links = []
    for anchor in row.find_all("a", href=True):
        href = anchor.get("href")
        links.append(
            {
                "text": _clean(anchor.get_text(" ", strip=True)),
                "href": urljoin(DIBBS_BASE_URL, href) if href else None,
            }
        )
    return links


def _parse_result_row(row) -> DibbsCustomQueryResult | None:
    cells = row.find_all("td")
    if len(cells) < 8:
        return None

    row_number = _clean(cells[0].get_text(" ", strip=True))
    if not row_number or not row_number.isdigit():
        return None

    links = _row_links(row)
    nsn_link = next((link for link in links if re.search(r"RFQNsn\.aspx", link.get("href") or "", re.I)), None)
    pdf_link = next((link for link in links if re.search(r"\.PDF$", link.get("href") or "", re.I)), None)
    package_link = next((link for link in links if "rfqrec.aspx" in (link.get("href") or "").lower()), None)

    pr_text = _clean(cells[6].get_text(" ", strip=True)) or ""
    quantity_match = re.search(r"QTY:\s*([0-9.,]+)", pr_text, re.I)
    pr_number = _clean(re.sub(r"QTY:\s*[0-9.,]+", "", pr_text, flags=re.I))

    return DibbsCustomQueryResult(
        nsn=_clean(cells[1].get_text(" ", strip=True)),
        nomenclature=_clean(cells[2].get_text(" ", strip=True)),
        technical_documents=_clean(cells[3].get_text(" ", strip=True)),
        solicitation_number=_clean(pdf_link["text"] if pdf_link else cells[4].get_text(" ", strip=True)),
        pdf_url=pdf_link["href"] if pdf_link else None,
        package_url=package_link["href"] if package_link else None,
        status=_clean_status(cells[5].get_text(" ", strip=True)),
        pr_number=pr_number,
        quantity=quantity_match.group(1) if quantity_match else None,
        issue_date=_clean(cells[7].get_text(" ", strip=True)),
        return_by_date=_clean(cells[8].get_text(" ", strip=True)) if len(cells) > 8 else None,
        detail_url=nsn_link["href"] if nsn_link else None,
    )


def _parse_results(html: str, limit: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for row in soup.select("table tr"):
        parsed = _parse_result_row(row)
        if parsed:
            rows.append(asdict(parsed))
        if len(rows) >= limit:
            break
    return rows


def search_dibbs_custom_query_by_fsc(fsc: str, limit: int = 25, headless: bool = True) -> dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = context.new_page()
        try:
            _goto_with_retry(page, DIBBS_RFQ_URL)
            _accept_warning_if_needed(page)
            _submit_fsc_custom_query(page, fsc)
            html = page.content()
            return {
                "fsc": str(fsc).strip(),
                "final_url": page.url,
                "title": page.title(),
                "results": _parse_results(html, limit),
            }
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    import json
    import sys

    fsc_arg = sys.argv[1] if len(sys.argv) > 1 else "6520"
    limit_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    print(json.dumps(search_dibbs_custom_query_by_fsc(fsc_arg, limit_arg), indent=2))
