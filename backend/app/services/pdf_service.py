from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from sqlalchemy.orm import Session
from playwright.sync_api import Response, sync_playwright

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile


def _safe_dirname(s: str) -> str:
    s = (s or "").strip().split("»")[0].strip()
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", s)
    return s or "opportunity"


def _safe_filename(s: str) -> str:
    s = (s or "").strip().split("»")[0].strip()
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
    s = s.split("»")[0].strip()
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


def _save_official_pdf(db: Session, opp: Opportunity, out_dir: Path, filename: str, source_url: str, data: bytes) -> tuple[int, str]:
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    if _already_downloaded(db, opp.id, filename):
        return 0, filename
    fp = out_dir / filename
    fp.write_bytes(data)
    db.add(OpportunityFile(
        opportunity_id=opp.id,
        file_type="PDF_OFFICIAL",
        filename=filename,
        source_url=source_url,
        file_path=str(fp.resolve()),
        created_at=datetime.utcnow(),
    ))
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
        db.add(OpportunityFile(
            opportunity_id=opp.id,
            file_type="PDF_FALLBACK_SNAPSHOT",
            filename=fname,
            source_url=page.url,
            file_path=str(fp.resolve()),
            created_at=datetime.utcnow(),
        ))
        db.commit()
        return 1, 0, None
    except Exception as e:
        return 0, 0, str(e)


class NetworkCapture:
    def __init__(self, sol_compact: str):
        self.sol_compact = (sol_compact or "").lower()
        self.events: list[dict[str, Any]] = []

    def handler(self, response: Response):
        try:
            url = response.url or ""
            ul = url.lower()
            if self.sol_compact in ul or ".pdf" in ul or "downloads/rfq/" in ul:
                headers = {}
                try:
                    headers = dict(response.headers)
                except Exception:
                    headers = {}
                body = b""
                try:
                    body = response.body()
                except Exception:
                    body = b""
                self.events.append({
                    "url": url,
                    "status": getattr(response, "status", None),
                    "headers": headers,
                    "body_prefix": body[:200].decode("latin-1", errors="replace"),
                    "is_pdf": _sniff_pdf_bytes(body),
                    "body_len": len(body),
                })
        except Exception:
            pass


def _candidate_locators(page, sol_compact: str) -> list[dict[str, Any]]:
    selectors = [
        f"a[href*='{sol_compact}.PDF']",
        f"a[href*='{sol_compact.lower()}.pdf']",
        f"a:has-text('{sol_compact}')",
        "a[href*='Downloads/RFQ']",
        "a[href*='.PDF']",
        "a[href*='.pdf']",
    ]
    out = []
    seen = set()
    target = (sol_compact or "").lower()

    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 5)
            for i in range(count):
                el = loc.nth(i)
                href = el.get_attribute("href")
                try:
                    text = (el.inner_text(timeout=1500) or "").strip()
                except Exception:
                    text = None

                href_l = (href or "").lower()
                text_l = (text or "").lower()
                if target and target not in href_l and target not in text_l:
                    continue

                key = (sel, href, text, i)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"selector": sel, "href": href, "text": text, "index": i})
        except Exception:
            continue
    return out


def _cookie_dict_from_playwright(cookies: list[dict[str, Any]]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value")}


def _download_via_requests(pdf_url: str, referer: str, cookies: list[dict[str, Any]], timeout_s: int = 15) -> dict[str, Any]:
    cookie_dict = _cookie_dict_from_playwright(cookies)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "Referer": referer,
        "Accept": "application/pdf,application/octet-stream,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    try:
        r = requests.get(pdf_url, headers=headers, cookies=cookie_dict, timeout=timeout_s, allow_redirects=True)
        body = r.content or b""
        meta = {
            "final_url": r.url,
            "status_code": r.status_code,
            "headers": dict(r.headers),
            "body_prefix": body[:200].decode("latin-1", errors="replace"),
            "is_pdf": _sniff_pdf_bytes(body),
        }
        if r.ok and _sniff_pdf_bytes(body):
            return {"ok": True, "pdf_bytes": body, "filename": Path(pdf_url.split("?")[0]).name or "official.pdf", "source_url": pdf_url, "details": meta}
        return {"ok": False, "reason": "cookie_request_not_pdf", "details": meta}
    except Exception as e:
        return {"ok": False, "reason": str(e), "details": {}}


def _run_strategy(page, candidate: dict[str, Any], strategy_name: str, timeout_ms: int = 5000) -> dict[str, Any]:
    href = candidate.get("href")
    text = candidate.get("text")
    sel = candidate.get("selector")
    idx = candidate.get("index", 0)
    details = {"strategy": strategy_name, "selector": sel, "href": href, "text": text, "index": idx}

    try:
        el = page.locator(sel).nth(idx)
    except Exception as e:
        return {"ok": False, "reason": str(e), "details": details}

    if strategy_name == "expect_download_click":
        try:
            with page.expect_download(timeout=timeout_ms) as info:
                el.click(timeout=3000)
            dl = info.value
            filename = dl.suggested_filename or Path((href or "official.pdf")).name or "official.pdf"
            p = dl.path()
            if not p:
                return {"ok": False, "reason": "download_no_path", "details": details}
            data = Path(p).read_bytes()
            if not _sniff_pdf_bytes(data):
                return {"ok": False, "reason": "download_not_pdf", "details": details}
            return {"ok": True, "pdf_bytes": data, "filename": filename, "source_url": href or page.url, "details": details}
        except Exception as e:
            return {"ok": False, "reason": str(e), "details": details}

    if strategy_name == "expect_response_click":
        try:
            with page.expect_response(
                lambda r: (".pdf" in (r.url or "").lower()) or ("downloads/rfq/" in (r.url or "").lower()),
                timeout=timeout_ms,
            ) as info:
                el.click(timeout=3000)
            r = info.value
            data = r.body()
            details["response_url"] = r.url
            details["status"] = getattr(r, "status", None)
            if not _sniff_pdf_bytes(data):
                return {"ok": False, "reason": "response_not_pdf", "details": details}
            filename = Path((r.url or href or "official.pdf").split("?")[0]).name or "official.pdf"
            return {"ok": True, "pdf_bytes": data, "filename": filename, "source_url": r.url or href or page.url, "details": details}
        except Exception as e:
            return {"ok": False, "reason": str(e), "details": details}

    if strategy_name == "js_dispatch_click_with_response":
        try:
            with page.expect_response(
                lambda r: (".pdf" in (r.url or "").lower()) or ("downloads/rfq/" in (r.url or "").lower()),
                timeout=timeout_ms,
            ) as info:
                page.evaluate(
                    """({selector, index}) => {
                        const nodes = Array.from(document.querySelectorAll(selector));
                        const el = nodes[index];
                        if (!el) throw new Error('js_target_not_found');
                        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                    }""",
                    {"selector": sel, "index": idx},
                )
            r = info.value
            data = r.body()
            details["response_url"] = r.url
            details["status"] = getattr(r, "status", None)
            if not _sniff_pdf_bytes(data):
                return {"ok": False, "reason": "response_not_pdf", "details": details}
            filename = Path((r.url or href or "official.pdf").split("?")[0]).name or "official.pdf"
            return {"ok": True, "pdf_bytes": data, "filename": filename, "source_url": r.url or href or page.url, "details": details}
        except Exception as e:
            return {"ok": False, "reason": str(e), "details": details}

    if strategy_name == "expect_popup_then_page_pdf":
        popup = None
        try:
            with page.expect_popup(timeout=timeout_ms) as info:
                el.click(timeout=3000)
            popup = info.value
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
            details["popup_url"] = popup.url
            return {"ok": False, "reason": "popup_opened_no_bytes", "details": details}
        except Exception as e:
            return {"ok": False, "reason": str(e), "details": details}
        finally:
            if popup:
                try:
                    popup.close()
                except Exception:
                    pass

    return {"ok": False, "reason": "unknown_strategy", "details": details}


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
    out_dir = _ensure_dir(Path(base_dir) / folder / "pdfs")

    created = 0
    skipped = 0
    errors: list[str] = []
    official_pdf_saved = False
    official_pdf_filename = None
    official_pdf_error = None
    debug_log_path = None
    detail_url = f"https://dibbs2.bsm.dla.mil/Downloads/RFQ/5/{sol_compact}.PDF" if sol_compact else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        page.goto(opp.url, wait_until="domcontentloaded", timeout=60000)
        _stabilize_dibbs_page(page, opp)

        net = NetworkCapture(sol_compact)
        page.on("response", net.handler)

        debug_payload: dict[str, Any] = {
            "start_url": opp.url,
            "page_url_before_attempt": page.url,
            "solicitation_number": opp.solicitation_number,
            "detail_url": detail_url,
            "strategies": [],
            "network_events": [],
        }

        try:
            cookies = context.cookies(["https://www.dibbs.bsm.dla.mil", "https://dibbs2.bsm.dla.mil"])
        except Exception:
            cookies = []
        debug_payload["cookies"] = cookies

        candidates = _candidate_locators(page, sol_compact)[:2]
        debug_payload["candidates"] = candidates

        if detail_url:
            cookie_result = _download_via_requests(detail_url, page.url, cookies)
            debug_payload["strategies"].append({
                "candidate": {"selector": "direct_cookie_request", "href": detail_url, "text": None, "index": 0},
                "strategy": "direct_cookie_request",
                "ok": cookie_result.get("ok", False),
                "reason": cookie_result.get("reason"),
                "details": cookie_result.get("details"),
            })
            if cookie_result.get("ok"):
                data = cookie_result["pdf_bytes"]
                filename = cookie_result.get("filename") or f"{sol_compact}.PDF"
                source_url = cookie_result.get("source_url") or detail_url
                created_now, saved_name = _save_official_pdf(db, opp, out_dir, filename, source_url, data)
                created += created_now
                if created_now == 0:
                    skipped += 1
                official_pdf_saved = True
                official_pdf_filename = saved_name

        strategy_order = [
            "expect_download_click",
            "expect_response_click",
            "js_dispatch_click_with_response",
            "expect_popup_then_page_pdf",
        ]

        if not official_pdf_saved:
            for cand in candidates:
                for strat in strategy_order:
                    result = _run_strategy(page, cand, strat, timeout_ms=5000)
                    debug_payload["strategies"].append({
                        "candidate": cand,
                        "strategy": strat,
                        "ok": result.get("ok", False),
                        "reason": result.get("reason"),
                        "details": result.get("details"),
                    })
                    if result.get("ok"):
                        data = result["pdf_bytes"]
                        filename = result.get("filename") or f"{sol_compact}.PDF"
                        source_url = result.get("source_url") or detail_url or page.url
                        created_now, saved_name = _save_official_pdf(db, opp, out_dir, filename, source_url, data)
                        created += created_now
                        if created_now == 0:
                            skipped += 1
                        official_pdf_saved = True
                        official_pdf_filename = saved_name
                        break
                if official_pdf_saved:
                    break

        if not official_pdf_saved:
            debug_payload["network_events"] = net.events[:20]
            official_pdf_error = "all_strategies_failed"
            errors.append(f"{detail_url} -> {official_pdf_error}")

        debug_payload["page_url_after_attempt"] = page.url
        debug_payload["official_pdf_saved"] = official_pdf_saved
        debug_payload["official_pdf_filename"] = official_pdf_filename
        debug_payload["official_pdf_error"] = official_pdf_error

        try:
            debug_log_path = _write_debug_log(out_dir, opp, debug_payload)
        except Exception as e:
            debug_log_path = None
            errors.append(f"debug_log_write_failed -> {e}")

        snap_info = {"created": 0, "skipped": 0, "error": None, "url": page.url}
        if always_snapshot:
            c, s, e = _create_snapshot_pdf(db, opp, page, out_dir)
            created += c
            skipped += s
            snap_info = {"created": c, "skipped": s, "error": e, "url": page.url}

        context.close()
        browser.close()

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "start_url": opp.url,
        "detail_url": detail_url,
        "official_pdf_saved": official_pdf_saved,
        "official_pdf_filename": official_pdf_filename,
        "official_pdf_error": official_pdf_error,
        "debug_log_path": debug_log_path,
        "snapshot": snap_info if always_snapshot else None,
        "folder": str(out_dir),
    }
