from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

DIBBS_RFQ_FSC_URL = "https://www.dibbs.bsm.dla.mil/Rfq/RfqFsc.aspx"
DEFAULT_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
}


@contextmanager
def dibbs_page(headless: bool = True) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            extra_http_headers=DEFAULT_HEADERS,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            yield browser, context, page
        finally:
            context.close()
            browser.close()


def _first(page: Page, selectors: list[str]):
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


def _select_fsc_option(page: Page, fsc: str) -> bool:
    selectors = [
        "select[name='ctl00$cph1$lstValue']",
        "select[id='ctl00_cph1_lstValue']",
        "select[name='lstValue']",
    ]
    normalized_fsc = str(fsc).strip()

    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() == 0:
                continue

            options = loc.first.locator("option")
            option_count = options.count()
            for index in range(option_count):
                option = options.nth(index)
                value = (option.get_attribute("value") or "").strip()
                label = (option.text_content() or "").strip()
                if value == normalized_fsc or label.startswith(f"{normalized_fsc} -"):
                    loc.first.select_option(value=value or label)
                    return True
        except Exception:
            continue

    return False


def _click_ok_if_present(page: Page) -> None:
    selectors = [
        "text=OK",
        "input[value='OK']",
        "button:has-text('OK')",
        "a:has-text('OK')",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0:
                loc.first.click()
                page.wait_for_timeout(1200)
                page.wait_for_load_state("networkidle")
                return
        except Exception:
            continue


def _goto_with_retry(page: Page, url: str, attempts: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return
        except Exception as exc:
            last_error = exc
            if attempt >= attempts - 1:
                break
            try:
                page.wait_for_timeout(1500 * (attempt + 1))
            except Exception:
                pass
    if last_error:
        raise last_error


def open_dibbs_rfq_list(page: Page, fsc: str | None = None, debug: bool = False) -> None:
    _goto_with_retry(page, DIBBS_RFQ_FSC_URL)
    page.wait_for_timeout(1500)
    page.wait_for_load_state("networkidle")

    _click_ok_if_present(page)
    _click_ok_if_present(page)

    if not fsc:
        if debug:
            try:
                print("[DIBBS] final_url:", page.url)
                print("[DIBBS] title:", page.title())
            except Exception:
                pass
        return

    selected = _select_fsc_option(page, str(fsc))

    if not selected:
        input_selectors = [
            "input[name='ctl00$ContentPlaceHolder1$txtFSC']",
            "input[name='txtFSC']",
            "input[id*='txtFSC']",
            "input[placeholder*='FSC' i]",
            "input[aria-label*='FSC' i]",
            "input[type='text']",
        ]

        box = _first(page, input_selectors)
        if box is not None:
            try:
                box.fill("")
                box.fill(str(fsc))
            except Exception:
                pass

    submit_selectors = [
        "input[name='ctl00$ContentPlaceHolder1$btnSearch']",
        "input[type='submit']",
        "button[type='submit']",
        "input[value*='Search' i]",
        "input[value*='Submit' i]",
        "button:has-text('Search')",
        "button:has-text('Submit')",
        "a:has-text('Search')",
    ]

    btn = _first(page, submit_selectors)
    if btn is not None:
        try:
            btn.click()
            page.wait_for_timeout(2500)
            page.wait_for_load_state("networkidle")
            _click_ok_if_present(page)
        except Exception:
            pass

    if debug:
        try:
            print("[DIBBS] final_url:", page.url)
            print("[DIBBS] title:", page.title())
        except Exception:
            pass


def page_html(url: str, headless: bool = True) -> str:
    with dibbs_page(headless=headless) as (_, _, page):
        _goto_with_retry(page, url)
        page.wait_for_timeout(1200)
        page.wait_for_load_state("networkidle")
        _click_ok_if_present(page)
        _click_ok_if_present(page)
        return page.content()
