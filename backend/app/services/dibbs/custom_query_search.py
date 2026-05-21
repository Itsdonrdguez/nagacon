from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError

from app.services.dibbs.session import (
    _click_ok_if_present,
    _goto_with_retry,
    capture_dibbs_page_state,
    dibbs_debug_scope,
    dibbs_log,
    dibbs_page,
)
from app.services.dibbs.structured_detail_parser import extract_dibbs_set_aside_type_from_node

DIBBS_BASE_URL = "https://www.dibbs.bsm.dla.mil"
DIBBS_RFQ_URL = "https://www.dibbs.bsm.dla.mil/RFQ/"


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
    return _clean(value)


def _parse_mmddyyyy(value: str | None) -> date | None:
    value = _clean(value)
    if not value:
        return None
    for fmt in ("%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_sol(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    return value.replace("-", "").upper()


def _looks_like_nsn(value: str | None) -> bool:
    value = _clean(value)
    if not value:
        return False
    digits = re.sub(r"\D", "", value)
    return len(digits) == 13


def _looks_like_solicitation(value: str | None) -> bool:
    value = _clean(value)
    if not value:
        return False
    normalized = value.replace("-", "").upper()
    return bool(re.fullmatch(r"[A-Z0-9]{8,20}", normalized)) and not normalized.isdigit()


def _accept_warning_if_needed(page: Page) -> None:
    dibbs_log("custom_query.warning.begin", url=page.url)
    accepted = _click_ok_if_present(page)
    if accepted:
        dibbs_log("custom_query.warning.accepted", url=page.url)
    else:
        dibbs_log("custom_query.warning.not_present", url=page.url)
    dibbs_log("custom_query.warning.end", url=page.url)


def _submit_fsc_custom_query(page: Page, fsc: str) -> None:
    dibbs_log("custom_query.submit.begin", fsc=fsc, url=page.url)
    page.select_option("#ctl00_cph1_ddlCategory", "fsc")
    page.fill("#ctl00_cph1_txtValue", str(fsc).strip())
    page.select_option("#ctl00_cph1_ddlScope", "open")
    page.select_option("#ctl00_cph1_ddlSort", "return by date")
    capture_dibbs_page_state(page, "before_search_click", fsc=fsc)
    dibbs_log("custom_query.submit.click", fsc=fsc, url=page.url)
    page.click("#ctl00_cph1_butDbGo")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=3000)
    except PlaywrightTimeoutError:
        dibbs_log("custom_query.submit.domcontentloaded_timeout", fsc=fsc, url=page.url)
    page.wait_for_timeout(3000)
    capture_dibbs_page_state(page, "after_search_click", fsc=fsc)
    _wait_for_results_grid(page)
    page.wait_for_timeout(1200)
    dibbs_log("custom_query.submit.done", fsc=fsc, url=page.url)


def _wait_for_results_grid(page: Page) -> None:
    dibbs_log("custom_query.grid.wait.begin", url=page.url)
    try:
        page.wait_for_url(re.compile(r".*/Rfq/RfqRecs\.aspx", re.I), timeout=60000)
    except PlaywrightTimeoutError:
        dibbs_log("custom_query.grid.wait.url_timeout", url=page.url)
        capture_dibbs_page_state(page, "results_url_timeout")
    try:
        page.wait_for_selector("table", timeout=30000)
    except PlaywrightTimeoutError:
        dibbs_log("custom_query.grid.wait.table_timeout", url=page.url)
        capture_dibbs_page_state(page, "results_table_timeout")
    dibbs_log("custom_query.grid.wait.end", url=page.url)


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


def _parse_result_row(row) -> dict[str, Any] | None:
    cells = row.find_all("td")
    if len(cells) < 9:
        return None

    row_number = _clean(cells[0].get_text(" ", strip=True))
    if not row_number or not row_number.isdigit():
        return None

    links = _row_links(row)
    nsn_link = next((link for link in links if re.search(r"RFQNsn\.aspx", link.get("href") or "", re.I)), None)
    pdf_link = next((link for link in links if re.search(r"\.PDF$", link.get("href") or "", re.I)), None)
    package_link = next((link for link in links if "rfqrec.aspx" in (link.get("href") or "").lower()), None)
    if not (nsn_link or pdf_link or package_link):
        return None

    pr_text = _clean(cells[6].get_text(" ", strip=True)) or ""
    quantity_match = re.search(r"QTY:\s*([0-9.,]+)", pr_text, re.I)
    pr_number = _clean(re.sub(r"QTY:\s*[0-9.,]+", "", pr_text, flags=re.I))
    solicitation_number = _clean(pdf_link["text"] if pdf_link else cells[4].get_text(" ", strip=True))
    return_by = _clean(cells[8].get_text(" ", strip=True))
    nsn = _clean(cells[1].get_text(" ", strip=True))
    nomenclature = _clean(cells[2].get_text(" ", strip=True))
    issue_date = _clean(cells[7].get_text(" ", strip=True))

    if not _looks_like_nsn(nsn):
        return None
    if not _looks_like_solicitation(solicitation_number):
        return None
    if not nomenclature or nomenclature.isdigit():
        return None
    if issue_date and not _parse_mmddyyyy(issue_date):
        return None
    if return_by and not _parse_mmddyyyy(return_by):
        return None

    return {
        "nsn": nsn,
        "nomenclature": nomenclature,
        "technical_documents": _clean(cells[3].get_text(" ", strip=True)),
        "solicitation_number": solicitation_number,
        "normalized_solicitation_number": _normalize_sol(solicitation_number),
        "pdf_url": pdf_link["href"] if pdf_link else None,
        "package_url": package_link["href"] if package_link else None,
        "status": _clean_status(cells[5].get_text(" ", strip=True)),
        "pr_number": pr_number,
        "quantity": quantity_match.group(1) if quantity_match else None,
        "issue_date": issue_date,
        "return_by_date": return_by,
        "return_by_parsed": _parse_mmddyyyy(return_by),
        "detail_url": nsn_link["href"] if nsn_link else None,
        "set_aside_type": extract_dibbs_set_aside_type_from_node(row),
    }


def _parse_result_rows(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for row in soup.select("table tr"):
        parsed = _parse_result_row(row)
        if parsed:
            rows.append(parsed)
    return rows


def _page_content_with_retry(page: Page, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        try:
            dibbs_log("custom_query.page_content.begin", attempt=attempt + 1, attempts=attempts, url=page.url)
            return page.content()
        except PlaywrightError as exc:
            last_error = exc
            dibbs_log(
                "custom_query.page_content.error",
                attempt=attempt + 1,
                attempts=attempts,
                error=str(exc),
                url=page.url,
            )
            if attempt < attempts - 1:
                page.wait_for_timeout(1500)
                continue
    if last_error:
        raise last_error
    return ""


def _available_page_numbers(html: str) -> list[int]:
    soup = BeautifulSoup(html, "html.parser")
    pages = {1}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href") or ""
        match = re.search(r"Page\$(\d+)", href)
        if match:
            pages.add(int(match.group(1)))
    return sorted(pages)


def _go_to_page(page: Page, page_number: int) -> bool:
    dibbs_log("playwright.page.begin", page_number=page_number, url=page.url)
    if page_number <= 1:
        try:
            page.evaluate(
                """({ target, arg }) => window.__doPostBack(target, arg)""",
                {"target": "ctl00$cph1$grdRfqSearch", "arg": "Page$First"},
            )
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            _wait_for_results_grid(page)
            page.wait_for_timeout(1000)
        except PlaywrightError:
            dibbs_log("playwright.page.error", page_number=page_number, url=page.url)
            return True
        dibbs_log("playwright.page.done", page_number=page_number, url=page.url)
        return True
    locator = page.locator(f'a[href*="Page${page_number}"]')
    if locator.count() > 0:
        locator.first.click()
    else:
        try:
            page.evaluate(
                """({ target, arg }) => window.__doPostBack(target, arg)""",
                {"target": "ctl00$cph1$grdRfqSearch", "arg": f"Page${page_number}"},
            )
        except PlaywrightError:
            dibbs_log("playwright.page.error", page_number=page_number, url=page.url)
            return False
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    _wait_for_results_grid(page)
    page.wait_for_timeout(1000)
    dibbs_log("playwright.page.done", page_number=page_number, url=page.url)
    return True


def _go_to_last_page(page: Page) -> bool:
    locator = page.locator('a[href*="Page$Last"]')
    if locator.count() == 0:
        dibbs_log("playwright.last_page.missing", url=page.url)
        return False
    dibbs_log("playwright.last_page.begin", url=page.url)
    locator.first.click()
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    _wait_for_results_grid(page)
    page.wait_for_timeout(1200)
    dibbs_log("playwright.last_page.done", url=page.url)
    return True


def _parse_current_result_rows(page: Page, attempts: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for attempt in range(max(1, attempts)):
        dibbs_log("playwright.parse.begin", attempt=attempt + 1, attempts=attempts, url=page.url)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        try:
            html = _page_content_with_retry(page)
        except PlaywrightError:
            dibbs_log("playwright.parse.page_content_error", attempt=attempt + 1, attempts=attempts, url=page.url)
            capture_dibbs_page_state(page, "parse_page_content_error", attempt=attempt + 1)
            if attempt < attempts - 1:
                page.wait_for_timeout(1500)
                continue
            raise
        rows = _parse_result_rows(html)
        if rows:
            dibbs_log("playwright.parse.rows", attempt=attempt + 1, attempts=attempts, row_count=len(rows), url=page.url)
            return rows

        if "No Records Found" in html or "No records found" in html:
            dibbs_log("playwright.parse.no_records", attempt=attempt + 1, attempts=attempts, url=page.url)
            return []
        if attempt < attempts - 1:
            dibbs_log("playwright.parse.retry", attempt=attempt + 1, attempts=attempts, url=page.url)
            page.wait_for_timeout(1500)
            capture_dibbs_page_state(page, "parse_retry", attempt=attempt + 1)
    dibbs_log("playwright.parse.end", attempts=attempts, row_count=len(rows), url=page.url)
    return rows


def search_dibbs_custom_query_by_fsc(
    fsc: str,
    limit: int = 25,
    max_pages: int = 4,
    include_past_due: bool = False,
    all_results: bool = False,
    headless: bool = True,
    debug: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with dibbs_debug_scope(debug):
        dibbs_log(
            "search.begin",
            all_results=all_results,
            fsc=str(fsc or "").strip(),
            include_past_due=include_past_due,
            limit=limit,
            max_pages=max_pages,
        )
        today = date.today()
        fsc_value = str(fsc or "").strip()
        diagnostics: dict[str, Any] = {
            "request_fsc": fsc_value,
            "request_limit": limit,
            "max_pages": max_pages,
            "all_results": all_results,
            "mode": "custom_query_fsc",
            "pages_scanned": [],
            "rows_seen": 0,
            "rows_filtered_past_due": 0,
            "rows_parsed": 0,
            "final_url": None,
            "page_title": None,
            "transport": "playwright",
        }
        if not fsc_value:
            return [], diagnostics

        collected: list[dict[str, Any]] = []
        seen_solicitations: set[str] = set()

        with dibbs_page(headless=headless) as (_, _, page):
            try:
                dibbs_log("playwright_search.begin", fsc=fsc_value, headless=headless)
                _goto_with_retry(page, DIBBS_RFQ_URL)
                _accept_warning_if_needed(page)
                _submit_fsc_custom_query(page, fsc_value)
                diagnostics["final_url"] = page.url
                diagnostics["page_title"] = page.title()
                dibbs_log("playwright_search.results.ready", fsc=fsc_value, title=diagnostics["page_title"], url=page.url)

                if _go_to_last_page(page):
                    diagnostics["used_last_page_jump"] = True
                else:
                    diagnostics["used_last_page_jump"] = False

                initial_html = _page_content_with_retry(page)
                page_numbers = _available_page_numbers(initial_html)
                dibbs_log(
                    "playwright_search.pages.discovered",
                    fsc=fsc_value,
                    page_numbers=page_numbers,
                    used_last_page_jump=diagnostics["used_last_page_jump"],
                )
                if all_results:
                    last_page = max(page_numbers) if page_numbers else 1
                    scan_pages = list(range(last_page, 0, -1))
                else:
                    scan_pages = sorted(page_numbers, reverse=True)[: max(1, max_pages)]
                dibbs_log("playwright_search.pages.selected", fsc=fsc_value, scan_pages=scan_pages)

                for index, page_number in enumerate(scan_pages):
                    if not (all_results and index == 0 and diagnostics["used_last_page_jump"]):
                        if not _go_to_page(page, page_number):
                            continue
                    diagnostics["pages_scanned"].append(page_number)
                    rows = _parse_current_result_rows(page)
                    diagnostics["rows_seen"] += len(rows)
                    dibbs_log("playwright_search.page.rows", fsc=fsc_value, page_number=page_number, row_count=len(rows))

                    for row in rows:
                        return_by_date = row.get("return_by_parsed")
                        if not include_past_due and return_by_date and return_by_date < today:
                            diagnostics["rows_filtered_past_due"] += 1
                            continue
                        sol_key = row.get("normalized_solicitation_number") or row.get("solicitation_number") or row.get("detail_url")
                        if sol_key in seen_solicitations:
                            continue
                        seen_solicitations.add(sol_key)
                        collected.append(row)
                        if not all_results and len(collected) >= limit:
                            diagnostics["rows_parsed"] = len(collected)
                            dibbs_log("playwright_search.done", fsc=fsc_value, rows_parsed=len(collected))
                            return collected, diagnostics
            except Exception as exc:
                capture_dibbs_page_state(page, "playwright_search_exception", fsc=fsc_value, error=str(exc))
                raise

        diagnostics["rows_parsed"] = len(collected)
        dibbs_log("playwright_search.done", fsc=fsc_value, rows_parsed=len(collected))
        return collected, diagnostics
