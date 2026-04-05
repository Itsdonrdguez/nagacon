from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

DIBBS_RFQ_FSC_URL = "https://www.dibbs.bsm.dla.mil/Rfq/RfqFsc.aspx"


@contextmanager
def dibbs_page(headless: bool = True) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
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


def open_dibbs_rfq_list(page: Page, fsc: str | None = None, debug: bool = False) -> None:
    page.goto(DIBBS_RFQ_FSC_URL, wait_until="domcontentloaded")
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
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        page.wait_for_load_state("networkidle")
        _click_ok_if_present(page)
        _click_ok_if_present(page)
        return page.content()
