from __future__ import annotations

"""
DIBBS detail enrichment (Windows-safe) with Return-By parsing.

Observed:
- Many DIBBS "RFQ NSN" pages include a "Solicitations" table with columns:
  Solicitation # | PR # | QTY | Issue | Return By
- The URL looks like RFQNsn.aspx?value=<NSN>...
- We can extract posted_at (Issue) and due_at (Return By) by matching the row
  for the current solicitation number.

This file is used by POST /api/dibbs/enrich.
"""

import asyncio
import re
import sys
from datetime import datetime
from typing import Any, Optional, Tuple

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_DOMAIN = "www.dibbs.bsm.dla.mil"

# Fallback date patterns (mm-dd-yyyy etc.)
DATE_PATTERNS = [
    re.compile(r"\b(?P<m>\d{1,2})[/-](?P<d>\d{1,2})[/-](?P<y>\d{4})\b"),
    re.compile(r"\b(?P<d>\d{1,2})-(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(?P<y>\d{4})\b", re.I),
    re.compile(r"\b(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(?P<d>\d{1,2}),\s*(?P<y>\d{4})\b", re.I),
]

KEYWORDS_DUE = ["return by", "closing date", "response date", "quote due", "offers due", "due date", "closing"]
KEYWORDS_POSTED = ["issue", "issue date", "posted", "solicitation issue date"]


def normalize_solicitation_number(sol: str | None) -> str:
    s = (sol or "").strip()
    if "»" in s:
        s = s.split("»", 1)[0].strip()
    if s.lower().endswith("package view"):
        s = s[:-len("package view")].strip()
    return s


def _sol_key(sol: str | None) -> str:
    # SPE2DS-26-T-3953  -> SPE2DS26T3953
    return re.sub(r"[^A-Za-z0-9]+", "", (sol or "").upper())


async def _accept_dod_warning_if_present(page) -> None:
    if "dodwarning.aspx" not in page.url.lower():
        return
    candidates = [
        "input[type=submit][value*='OK' i]",
        "input[type=submit][value*='Agree' i]",
        "input[type=submit][value*='I Agree' i]",
        "button:has-text('OK')",
        "button:has-text('Agree')",
        "button:has-text('I Agree')",
        "input[type=submit]",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                break
        except Exception:
            continue
    try:
        await page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)


def _parse_date_token(token: str) -> Optional[datetime]:
    t = (token or "").strip()
    if not t or t.lower() == "none":
        return None
    for pat in DATE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        gd = m.groupdict()
        try:
            if "m" in gd:
                return datetime(int(gd["y"]), int(gd["m"]), int(gd["d"]))
            mon_map = {k.lower(): i for i, k in enumerate(
                ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], start=1
            )}
            mon = mon_map[gd["mon"].lower()[:3]]
            return datetime(int(gd["y"]), int(mon), int(gd["d"]))
        except Exception:
            return None
    return None


def _parse_first_date_near_keywords(text: str, keywords: list[str]) -> Optional[datetime]:
    t = text or ""
    low = t.lower()
    hits = []
    for kw in keywords:
        idx = low.find(kw)
        if idx == -1:
            continue
        window = t[idx: idx + 300]
        for pat in DATE_PATTERNS:
            m = pat.search(window)
            if m:
                hits.append((idx, m.group(0)))
                break
    if not hits:
        return None
    _, token = sorted(hits, key=lambda x: x[0])[0]
    return _parse_date_token(token)


def _extract_issue_return_by(soup: BeautifulSoup, solicitation_number: str | None) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Attempts to parse the "Solicitations" table on the RFQ NSN page and match the row
    for the given solicitation number.
    """
    target = _sol_key(solicitation_number)
    if not target:
        return None, None

    # Find a table that includes header "Solicitation #" and "Return By"
    tables = soup.find_all("table")
    for table in tables:
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        if not any("solicitation" in h for h in headers):
            continue
        if not any("return by" in h for h in headers):
            continue
        if not any(h.strip() == "issue" or "issue" in h for h in headers):
            continue

        # Map header index
        def idx_of(name_contains: str) -> int | None:
            for i, h in enumerate(headers):
                if name_contains in h:
                    return i
            return None

        i_sol = idx_of("solicitation")
        i_issue = idx_of("issue")
        i_return = idx_of("return by")
        if i_sol is None or i_issue is None or i_return is None:
            continue

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < max(i_sol, i_issue, i_return) + 1:
                continue

            sol_txt = tds[i_sol].get_text(" ", strip=True)
            if _sol_key(sol_txt) != target:
                continue

            issue_txt = tds[i_issue].get_text(" ", strip=True)
            return_txt = tds[i_return].get_text(" ", strip=True)

            return _parse_date_token(issue_txt), _parse_date_token(return_txt)

    return None, None


async def fetch_package_details(url: str, solicitation_number: str | None = None) -> dict[str, Any]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            locale="en-US",
        )

        try:
            await context.add_cookies([{
                "name": "DIBBSDoDWarning",
                "value": "AGREE",
                "domain": BASE_DOMAIN,
                "path": "/",
                "secure": True,
            }])
        except Exception:
            pass

        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await _accept_dod_warning_if_present(page)
        try:
            await page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            pass
        await page.wait_for_timeout(1200)

        html = await page.content()
        await context.close()
        await browser.close()

    soup = BeautifulSoup(html, "lxml")
    raw_text = soup.get_text("\n", strip=True)

    # Best path: parse the solicitations table by matching solicitation number
    posted_at, due_at = _extract_issue_return_by(soup, solicitation_number)

    # Fallback: keyword proximity search on raw text
    if due_at is None:
        due_at = _parse_first_date_near_keywords(raw_text, KEYWORDS_DUE)
    if posted_at is None:
        posted_at = _parse_first_date_near_keywords(raw_text, KEYWORDS_POSTED)

    return {
        "raw_text": raw_text,
        "due_at": due_at,
        "posted_at": posted_at,
        "page_title": soup.title.get_text(" ", strip=True) if soup.title else "",
    }


def fetch_package_details_sync(url: str, solicitation_number: str | None = None) -> dict[str, Any]:
    # Force Proactor policy in this thread, then run in a fresh loop.
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
        except Exception:
            pass
    return asyncio.run(fetch_package_details(url, solicitation_number=solicitation_number))
