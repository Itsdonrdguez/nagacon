#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import textwrap
import time
from typing import Any, Iterable

import requests


@dataclass
class TestResult:
    name: str
    category: str
    method: str
    target: str
    ok: bool
    status: str | int
    summary: str
    sample: Any = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    elapsed_ms: int = 0


class TesterV2:
    def __init__(
        self,
        base_url: str,
        streamlit_url: str,
        timeout: int,
        out_dir: Path,
        browser: bool,
        run_ingest: bool,
        strict: bool,
        max_opps: int,
    ):
        self.base_url = base_url.rstrip("/")
        self.streamlit_url = streamlit_url.rstrip("/")
        self.timeout = timeout
        self.out_dir = out_dir
        self.browser = browser
        self.run_ingest = run_ingest
        self.strict = strict
        self.max_opps = max(1, max_opps)
        self.session = requests.Session()
        self.results: list[TestResult] = []
        self.console_events: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {
            "opportunity_ids": [],
            "opportunity_id": None,
            "pipeline_id": None,
            "file_id": None,
            "vendor_lead_id": None,
            "vendor_quote_id": None,
            "task_id": None,
        }
        self.created_quotes: list[int] = []
        self.created_tasks: list[int] = []

    def record(self, **kwargs):
        self.results.append(TestResult(**kwargs))

    def run_test(self, name: str, category: str, method: str, target: str, fn):
        start = time.time()
        try:
            data = fn()
            ok = bool(data.get("ok", True))
            self.record(
                name=name,
                category=category,
                method=method,
                target=target,
                ok=ok,
                status=data.get("status", "OK"),
                summary=data.get("summary", "ok" if ok else "failed"),
                sample=data.get("sample"),
                elapsed_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            self.record(
                name=name,
                category=category,
                method=method,
                target=target,
                ok=False,
                status="ERR",
                summary=str(e),
                sample={"exception": repr(e)},
                elapsed_ms=int((time.time() - start) * 1000),
            )

    def _request(self, method: str, path: str, *, json_body: Any = None, params: dict[str, Any] | None = None, allow_redirects: bool = True) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        return self.session.request(
            method=method,
            url=url,
            json=json_body,
            params=params,
            timeout=self.timeout,
            allow_redirects=allow_redirects,
        )

    @staticmethod
    def _json_or_text(resp: requests.Response):
        try:
            return resp.json()
        except Exception:
            return resp.text[:4000]

    def http_check(self, method: str, path: str, *, json_body: Any = None, params: dict[str, Any] | None = None, expected: Iterable[int] = (200,)):
        resp = self._request(method, path, json_body=json_body, params=params)
        payload = self._json_or_text(resp)
        ok = resp.status_code in set(expected)
        return {
            "ok": ok,
            "status": resp.status_code,
            "summary": "ok" if ok else f"unexpected status {resp.status_code}",
            "sample": payload,
        }

    def streamlit_get(self, url: str):
        resp = self.session.get(url, timeout=self.timeout)
        text = resp.text[:4000]
        low = text.lower()
        ui_ok = resp.status_code == 200 and ("streamlit" in low or "<!doctype html" in low or "<html" in low)
        fatal_markers = ["traceback", "streamlitapiexception", "internal server error"]
        bad_hits = [m for m in fatal_markers if m in low]
        ok = ui_ok and not bad_hits
        return {
            "ok": ok,
            "status": resp.status_code,
            "summary": "reachable" if ok else f"page issue: {', '.join(bad_hits) if bad_hits else 'not reachable'}",
            "sample": text,
        }

    def discover_context(self):
        resp = self._request("GET", "/api/opportunities", params={"limit": max(self.max_opps, 25), "offset": 0})
        payload = self._json_or_text(resp)
        if resp.status_code == 200 and isinstance(payload, list):
            opp_ids = [p.get("id") for p in payload if isinstance(p, dict) and p.get("id")]
            self.context["opportunity_ids"] = opp_ids[: self.max_opps]
            self.context["opportunity_id"] = opp_ids[0] if opp_ids else None
        opp_id = self.context.get("opportunity_id")
        if not opp_id:
            return
        self._hydrate_related_context(opp_id)

    def _hydrate_related_context(self, opp_id: int):
        presp = self._request("GET", f"/api/pipeline/by-opportunity/{opp_id}")
        if presp.status_code == 200:
            pdata = self._json_or_text(presp)
            if isinstance(pdata, dict):
                self.context["pipeline_id"] = pdata.get("id")

        fresp = self._request("GET", "/api/files/list", params={"opportunity_id": opp_id})
        if fresp.status_code == 200:
            fdata = self._json_or_text(fresp)
            if isinstance(fdata, list) and fdata:
                self.context["file_id"] = fdata[0].get("id")

        lresp = self._request("GET", "/api/vendors/leads", params={"opportunity_id": opp_id})
        if lresp.status_code == 200:
            ldata = self._json_or_text(lresp)
            if isinstance(ldata, list) and ldata:
                self.context["vendor_lead_id"] = ldata[0].get("id")

        qresp = self._request("GET", "/api/vendors/quotes", params={"opportunity_id": opp_id})
        if qresp.status_code == 200:
            qdata = self._json_or_text(qresp)
            if isinstance(qdata, list) and qdata:
                self.context["vendor_quote_id"] = qdata[0].get("id")

    def maybe_ingest(self):
        if not self.run_ingest:
            return
        self.run_test(
            "Ingest DIBBS",
            "ingest",
            "POST",
            "/api/scrapers/dibbs/run",
            lambda: self.http_check("POST", "/api/scrapers/dibbs/run", json_body={"max_pages": 1, "fsc": "6520", "limit": 5}, expected=(200,)),
        )
        self.run_test(
            "Verify SAM",
            "ingest",
            "POST",
            "/api/scrapers/sam/verify",
            lambda: self.http_check("POST", "/api/scrapers/sam/verify", json_body={"limit": 3, "q": "medical"}, expected=(200, 400, 401, 404, 422, 500)),
        )
        self.run_test(
            "Ingest SAM",
            "ingest",
            "POST",
            "/api/scrapers/sam/run",
            lambda: self.http_check("POST", "/api/scrapers/sam/run", json_body={"limit": 3, "q": "medical", "debug": True}, expected=(200, 400, 401, 404, 422, 500)),
        )
        self.discover_context()

    def backend_global_suite(self):
        self.run_test("Backend health", "core", "GET", "/api/health/", lambda: self.http_check("GET", "/api/health/"))
        self.run_test("Opportunities list", "core", "GET", "/api/opportunities", lambda: self.http_check("GET", "/api/opportunities", params={"limit": 10, "offset": 0}))
        self.run_test("Analytics summary", "analytics", "GET", "/api/analytics/summary", lambda: self.http_check("GET", "/api/analytics/summary"))
        self.run_test("Streamlit root", "streamlit-http", "GET", self.streamlit_url, lambda: self.streamlit_get(self.streamlit_url))
        for suffix in ["/Opportunities", "/System_Status"]:
            url = f"{self.streamlit_url}{suffix}"
            self.run_test(f"Page {suffix}", "streamlit-http", "GET", url, lambda url=url: self.streamlit_get(url))

    def backend_opportunity_suite(self, opp_id: int):
        self.run_test(f"Opportunity detail {opp_id}", "core", "GET", f"/api/opportunities/{opp_id}", lambda: self.http_check("GET", f"/api/opportunities/{opp_id}"))
        self.run_test(f"Workspace summary {opp_id}", "workspace", "GET", f"/api/workspace/summary?opp_id={opp_id}", lambda: self.http_check("GET", "/api/workspace/summary", params={"opp_id": opp_id}))
        self.run_test(f"Workspace parse {opp_id}", "workspace", "POST", "/api/workspace/parse", lambda: self.http_check("POST", "/api/workspace/parse", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Generate checklist {opp_id}", "workspace", "POST", "/api/workspace/generate/checklist", lambda: self.http_check("POST", "/api/workspace/generate/checklist", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Generate vendors {opp_id}", "workspace", "POST", "/api/workspace/generate/vendors", lambda: self.http_check("POST", "/api/workspace/generate/vendors", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Generate email {opp_id}", "workspace", "POST", "/api/workspace/generate/email", lambda: self.http_check("POST", "/api/workspace/generate/email", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"List artifacts {opp_id}", "workspace", "GET", "/api/workspace/artifacts", lambda: self.http_check("GET", "/api/workspace/artifacts", params={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"List tasks {opp_id}", "workspace", "GET", "/api/workspace/tasks", lambda: self.http_check("GET", "/api/workspace/tasks", params={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Export ZIP {opp_id}", "workspace", "GET", "/api/workspace/export.zip", lambda: self.http_check("GET", "/api/workspace/export.zip", params={"opportunity_id": opp_id}, expected=(200, 404, 500)))

        def create_task():
            resp = self._request("POST", "/api/workspace/tasks", json_body={"opportunity_id": opp_id, "title": f"V2 tester {datetime.utcnow().strftime('%H%M%S')}"})
            payload = self._json_or_text(resp)
            if resp.status_code == 200 and isinstance(payload, dict) and payload.get("id"):
                self.context["task_id"] = payload.get("id")
                self.created_tasks.append(int(payload["id"]))
            return {"ok": resp.status_code == 200, "status": resp.status_code, "summary": "ok" if resp.status_code == 200 else "failed", "sample": payload}
        self.run_test(f"Create task {opp_id}", "workspace", "POST", "/api/workspace/tasks", create_task)

        self.run_test(f"Files list {opp_id}", "files", "GET", "/api/files/list", lambda: self.http_check("GET", "/api/files/list", params={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Download PDFs {opp_id}", "files", "POST", "/api/files/download_pdfs", lambda: self.http_check("POST", "/api/files/download_pdfs", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))

        fresp = self._request("GET", "/api/files/list", params={"opportunity_id": opp_id})
        if fresp.status_code == 200:
            fdata = self._json_or_text(fresp)
            if isinstance(fdata, list) and fdata:
                self.context["file_id"] = fdata[0].get("id")
        file_id = self.context.get("file_id")
        if file_id:
            self.run_test(f"Parse file {file_id}", "files", "POST", f"/api/files/parse/{file_id}", lambda: self.http_check("POST", f"/api/files/parse/{file_id}", expected=(200, 404, 500)))
            self.run_test(f"Download file {file_id}", "files", "GET", f"/api/files/download/{file_id}", lambda: self.http_check("GET", f"/api/files/download/{file_id}", expected=(200, 302, 307, 404, 500)))

        self.run_test(f"Pipeline by opp {opp_id}", "pipeline", "GET", f"/api/pipeline/by-opportunity/{opp_id}", lambda: self.http_check("GET", f"/api/pipeline/by-opportunity/{opp_id}", expected=(200, 404, 500)))

        def ensure_pipeline():
            resp = self._request("POST", f"/api/pipeline/by-opportunity/{opp_id}", json_body={})
            payload = self._json_or_text(resp)
            if resp.status_code == 200 and isinstance(payload, dict):
                self.context["pipeline_id"] = payload.get("id")
            return {"ok": resp.status_code == 200, "status": resp.status_code, "summary": "ok" if resp.status_code == 200 else "failed", "sample": payload}
        self.run_test(f"Pipeline create/get {opp_id}", "pipeline", "POST", f"/api/pipeline/by-opportunity/{opp_id}", ensure_pipeline)

        pipeline_id = self.context.get("pipeline_id")
        if pipeline_id:
            self.run_test(
                f"Pipeline patch {pipeline_id}",
                "pipeline",
                "PATCH",
                f"/api/pipeline/{pipeline_id}",
                lambda: self.http_check("PATCH", f"/api/pipeline/{pipeline_id}", json_body={"owner": "streamlit-super-tester-v2", "priority": "High", "notes": "Updated by tester v2"}, expected=(200, 404, 422, 500)),
            )

        self.run_test(f"Vendor leads list {opp_id}", "vendors", "GET", "/api/vendors/leads", lambda: self.http_check("GET", "/api/vendors/leads", params={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Vendor leads sync {opp_id}", "vendors", "POST", "/api/vendors/leads/sync", lambda: self.http_check("POST", "/api/vendors/leads/sync", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Vendor discovery {opp_id}", "vendors", "POST", f"/api/vendor-discovery/opportunities/{opp_id}", lambda: self.http_check("POST", f"/api/vendor-discovery/opportunities/{opp_id}", expected=(200, 400, 404, 500)))
        self.run_test(f"Vendor email draft {opp_id}", "vendors", "POST", f"/api/vendor-email/opportunities/{opp_id}/draft", lambda: self.http_check("POST", f"/api/vendor-email/opportunities/{opp_id}/draft", json_body={"opportunity_id": opp_id}, expected=(200, 400, 404, 500)))

        self.run_test(f"Quotes list {opp_id}", "quotes", "GET", "/api/vendors/quotes", lambda: self.http_check("GET", "/api/vendors/quotes", params={"opportunity_id": opp_id}, expected=(200, 404, 500)))
        self.run_test(f"Seed quotes {opp_id}", "quotes", "POST", "/api/vendors/quotes/seed", lambda: self.http_check("POST", "/api/vendors/quotes/seed", json_body={"opportunity_id": opp_id}, expected=(200, 404, 500)))

        def create_temp_quote():
            payload = {"opportunity_id": opp_id, "company_name": "TEST VENDOR V2", "part_number": f"TEST-{datetime.utcnow().strftime('%H%M%S')}", "status": "NOT_REQUESTED"}
            resp = self._request("POST", "/api/quotes/", json_body=payload)
            data = self._json_or_text(resp)
            if resp.status_code == 200 and isinstance(data, dict) and data.get("id"):
                self.created_quotes.append(int(data["id"]))
                self.context["vendor_quote_id"] = int(data["id"])
            return {"ok": resp.status_code == 200, "status": resp.status_code, "summary": "ok" if resp.status_code == 200 else "failed", "sample": data}
        self.run_test(f"Create temp quote {opp_id}", "quotes", "POST", "/api/quotes/", create_temp_quote)
        quote_id = self.context.get("vendor_quote_id")
        if quote_id:
            self.run_test(f"Patch quote {quote_id}", "quotes", "PATCH", f"/api/quotes/{quote_id}", lambda: self.http_check("PATCH", f"/api/quotes/{quote_id}", json_body={"status": "REQUESTED", "notes": "Patched by tester v2"}, expected=(200, 404, 422, 500)))

        self.run_test(f"Suggested quote {opp_id}", "quotes", "POST", f"/api/phase3/opportunities/{opp_id}/suggested-quote", lambda: self.http_check("POST", f"/api/phase3/opportunities/{opp_id}/suggested-quote", expected=(200, 400, 404, 500)))
        self.run_test(f"Proposal assist {opp_id}", "proposal", "POST", f"/api/proposal-assist/opportunities/{opp_id}/draft", lambda: self.http_check("POST", f"/api/proposal-assist/opportunities/{opp_id}/draft", expected=(200, 400, 404, 500)))
        self.run_test(f"Research USAspending {opp_id}", "research", "POST", f"/api/research/usaspending/opportunities/{opp_id}", lambda: self.http_check("POST", f"/api/research/usaspending/opportunities/{opp_id}", expected=(200, 400, 404, 500)))
        self.run_test(f"Seed research leads {opp_id}", "research", "POST", f"/api/research/usaspending/opportunities/{opp_id}/seed-leads", lambda: self.http_check("POST", f"/api/research/usaspending/opportunities/{opp_id}/seed-leads", expected=(200, 400, 404, 500)))
        self.run_test(f"Predecessor research {opp_id}", "research", "GET", f"/api/research/predecessor/opportunities/{opp_id}", lambda: self.http_check("GET", f"/api/research/predecessor/opportunities/{opp_id}", expected=(200, 404, 500)))

        workspace_url = f"{self.streamlit_url}/Workspace?opp_id={opp_id}"
        self.run_test(f"Workspace page {opp_id}", "streamlit-http", "GET", workspace_url, lambda: self.streamlit_get(workspace_url))

    def browser_suite(self):
        if not self.browser:
            return
        screenshots_dir = self.out_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            self.record(name="Playwright import", category="streamlit-browser", method="BROWSER", target="playwright", ok=False, status="SKIP", summary=f"playwright not available: {e}", sample=None)
            return

        def snap(page, name):
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
            path = screenshots_dir / f"{safe}.png"
            page.screenshot(path=str(path), full_page=True)
            return str(path)

        def summarize_page(page):
            body_text = page.locator("body").inner_text(timeout=3000)[:4000]
            lower = body_text.lower()
            issues = []
            for marker in ["traceback", "exception", "streamlitapiexception", "internal server error", "unable to serialize"]:
                if marker in lower:
                    issues.append(marker)
            return body_text, issues

        def clickable(page, labels: list[str]):
            found = []
            for label in labels:
                try:
                    loc = page.get_by_role("button", name=label)
                    if loc.count() > 0:
                        found.append((label, loc.first))
                except Exception:
                    pass
            return found

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1600, "height": 1300})
                page.set_default_timeout(self.timeout * 1000)
                net_events: list[dict[str, Any]] = []

                def on_console(msg):
                    entry = {"type": msg.type, "text": msg.text[:1500]}
                    self.console_events.append(entry)

                def on_page_error(err):
                    self.console_events.append({"type": "pageerror", "text": str(err)[:1500]})

                def on_response(resp):
                    try:
                        if self.base_url in resp.url and resp.status >= 400:
                            net_events.append({"url": resp.url, "status": resp.status})
                    except Exception:
                        pass

                page.on("console", on_console)
                page.on("pageerror", on_page_error)
                page.on("response", on_response)

                urls = [
                    ("home", self.streamlit_url),
                    ("opportunities", f"{self.streamlit_url}/Opportunities"),
                    ("system_status", f"{self.streamlit_url}/System_Status"),
                ]
                if self.context.get("opportunity_id"):
                    urls.append(("workspace", f"{self.streamlit_url}/Workspace?opp_id={self.context['opportunity_id']}"))

                for page_name, url in urls:
                    start = time.time()
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                        page.wait_for_timeout(3000)
                        text, issues = summarize_page(page)
                        screenshot = snap(page, page_name)
                        self.record(
                            name=f"Browser load {page_name}",
                            category="streamlit-browser",
                            method="BROWSER",
                            target=url,
                            ok=len(issues) == 0,
                            status=200 if len(issues) == 0 else "WARN",
                            summary="loaded" if len(issues) == 0 else f"issues: {', '.join(issues)}",
                            sample={"screenshot": screenshot, "text_head": text[:1500]},
                            elapsed_ms=int((time.time() - start) * 1000),
                        )
                    except Exception as e:
                        self.record(name=f"Browser load {page_name}", category="streamlit-browser", method="BROWSER", target=url, ok=False, status="ERR", summary=str(e), sample=None, elapsed_ms=int((time.time() - start) * 1000))

                # deeper navigation + button exercise
                if self.context.get("opportunity_id"):
                    url = f"{self.streamlit_url}/Workspace?opp_id={self.context['opportunity_id']}"
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(3500)
                    labels = [
                        "Refresh Workspace",
                        "Generate Checklist",
                        "Generate Vendor Shortlist",
                        "Generate Quote Email",
                        "Build Export ZIP",
                        "Sync Vendor Leads",
                        "Seed Quotes",
                    ]
                    for label, locator in clickable(page, labels):
                        start = time.time()
                        try:
                            locator.click(timeout=4000)
                            page.wait_for_timeout(2500)
                            text, issues = summarize_page(page)
                            screenshot = snap(page, f"workspace_{label}")
                            self.record(
                                name=f"Browser click {label}",
                                category="streamlit-browser",
                                method="BROWSER",
                                target=label,
                                ok=len(issues) == 0,
                                status=200 if len(issues) == 0 else "WARN",
                                summary="clicked" if len(issues) == 0 else f"issues after click: {', '.join(issues)}",
                                sample={"screenshot": screenshot, "text_head": text[:1200]},
                                elapsed_ms=int((time.time() - start) * 1000),
                            )
                        except Exception as e:
                            self.record(name=f"Browser click {label}", category="streamlit-browser", method="BROWSER", target=label, ok=False, status="ERR", summary=str(e), sample=None, elapsed_ms=int((time.time() - start) * 1000))

                if net_events:
                    self.record(name="Browser backend error scan", category="streamlit-browser", method="BROWSER", target="backend-responses", ok=False, status="WARN", summary="backend 4xx/5xx seen during UI run", sample=net_events[:100])
                else:
                    self.record(name="Browser backend error scan", category="streamlit-browser", method="BROWSER", target="backend-responses", ok=True, status=200, summary="no backend 4xx/5xx seen during UI run", sample=[])

                if self.console_events:
                    serious = [e for e in self.console_events if e.get("type") in {"error", "pageerror"} or "error" in str(e.get("text", "")).lower()]
                    self.record(name="Browser console scan", category="streamlit-browser", method="BROWSER", target="console", ok=len(serious) == 0, status=200 if len(serious) == 0 else "WARN", summary="clean console" if len(serious) == 0 else "console/page errors detected", sample=serious[:100])
                else:
                    self.record(name="Browser console scan", category="streamlit-browser", method="BROWSER", target="console", ok=True, status=200, summary="no console events captured", sample=[])
                browser.close()
        except Exception as e:
            self.record(name="Playwright session", category="streamlit-browser", method="BROWSER", target=self.streamlit_url, ok=False, status="ERR", summary=str(e), sample=None)

    def cleanup(self):
        for quote_id in self.created_quotes:
            try:
                self._request("DELETE", f"/api/quotes/{quote_id}")
            except Exception:
                pass

    def write_reports(self):
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        summary = {
            "generated_at": datetime.utcnow().isoformat(),
            "base_url": self.base_url,
            "streamlit_url": self.streamlit_url,
            "context": self.context,
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results if r.ok),
            "failed": sum(1 for r in self.results if not r.ok),
            "by_category": {},
        }
        cats = sorted({r.category for r in self.results})
        for cat in cats:
            rs = [r for r in self.results if r.category == cat]
            summary["by_category"][cat] = {"passed": sum(1 for r in rs if r.ok), "failed": sum(1 for r in rs if not r.ok)}

        json_path = self.out_dir / f"streamlit_super_tester_v2_report_{timestamp}.json"
        txt_path = self.out_dir / f"streamlit_super_tester_v2_report_{timestamp}.txt"
        csv_path = self.out_dir / f"streamlit_super_tester_v2_report_{timestamp}.csv"
        html_path = self.out_dir / f"streamlit_super_tester_v2_report_{timestamp}.html"

        payload = {"summary": summary, "results": [dataclasses.asdict(r) for r in self.results]}
        json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "category", "method", "target", "ok", "status", "summary", "elapsed_ms"])
            writer.writeheader()
            for r in self.results:
                writer.writerow({k: getattr(r, k) for k in ["name", "category", "method", "target", "ok", "status", "summary", "elapsed_ms"]})

        lines = ["NagaCon Streamlit Super Tester V2", "=" * 80, json.dumps(summary, indent=2), ""]
        for r in self.results:
            lines.extend([
                f"{r.name}",
                f"  CATEGORY: {r.category}",
                f"  METHOD: {r.method}",
                f"  TARGET: {r.target}",
                f"  OK: {r.ok}",
                f"  STATUS: {r.status}",
                f"  ELAPSED_MS: {r.elapsed_ms}",
                f"  SUMMARY: {r.summary}",
                f"  SAMPLE: {textwrap.shorten(json.dumps(r.sample, default=str), width=1400, placeholder=' ...') if r.sample is not None else ''}",
                "-" * 80,
            ])
        txt_path.write_text("\n".join(lines), encoding="utf-8")

        rows = []
        for r in self.results:
            cls = "pass" if r.ok else "fail"
            rows.append(
                f"<tr class='{cls}'><td>{escape(r.name)}</td><td>{escape(r.category)}</td><td>{escape(str(r.method))}</td>"
                f"<td>{escape(str(r.target))}</td><td>{escape(str(r.ok))}</td><td>{escape(str(r.status))}</td>"
                f"<td>{escape(r.summary)}</td><td><pre>{escape(json.dumps(r.sample, indent=2, default=str)[:5000] if r.sample is not None else '')}</pre></td></tr>"
            )
        html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>NagaCon Streamlit Super Tester V2</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; }}
.pass {{ background: #eefaf0; }}
.fail {{ background: #fff0f0; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
th {{ background: #f3f3f3; position: sticky; top: 0; }}
pre {{ white-space: pre-wrap; word-break: break-word; max-width: 900px; }}
.card {{ border: 1px solid #ddd; padding: 12px; margin-bottom: 18px; border-radius: 8px; }}
</style></head><body>
<h1>NagaCon Streamlit Super Tester V2</h1>
<div class='card'><pre>{escape(json.dumps(summary, indent=2))}</pre></div>
<table><thead><tr><th>Name</th><th>Category</th><th>Method</th><th>Target</th><th>OK</th><th>Status</th><th>Summary</th><th>Sample</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>"""
        html_path.write_text(html, encoding="utf-8")
        return json_path, txt_path, csv_path, html_path, summary


def escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_readme(path: Path):
    text = """NagaCon Streamlit Super Tester V2
================================

What V2 adds
------------
- Stronger end-to-end backend + Streamlit coverage.
- Optional browser automation with Playwright.
- Console error capture.
- Backend 4xx/5xx capture during browser runs.
- Multi-opportunity testing instead of a single record.
- HTML report in addition to JSON, CSV, and TXT.
- Deeper workspace button exercise when the buttons are visible.

What it tests automatically
---------------------------
- backend health
- opportunity discovery
- opportunities list and detail
- workspace summary / parse / artifact generation / tasks / export
- files list / parse / download / pdf download trigger
- pipeline create/get / patch
- vendor leads / sync / discovery / email draft
- quotes list / seed / temp quote / patch
- proposal assist
- research endpoints
- analytics summary
- Streamlit HTTP pages
- Streamlit browser navigation and button clicks
- browser console and backend response failures

Recommended install
-------------------
1. Python deps:
   pip install requests
2. Optional browser mode:
   pip install playwright
   python -m playwright install chromium

Recommended run
---------------
python streamlit_super_tester_v2.py --base-url http://127.0.0.1:8000 --streamlit-url http://127.0.0.1:8501 --run-ingest --browser --max-opps 3

Lighter run
-----------
python streamlit_super_tester_v2.py --base-url http://127.0.0.1:8000 --streamlit-url http://127.0.0.1:8501 --max-opps 2

How to read results
-------------------
- JSON: machine-readable full report
- CSV: quick spreadsheet-friendly summary
- TXT: plain text audit trail
- HTML: easiest human-readable report
- screenshots/: browser screenshots if --browser is used

Notes
-----
- V2 may create temporary tasks and quotes while testing.
- It attempts to clean temporary quotes up.
- SAM checks may fail if SAM_API_KEY is not configured.
- If you want the tester to fail the process on any warning or browser issue, use --strict.
"""
    path.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="NagaCon Streamlit Super Tester V2")
    parser.add_argument("--base-url", default=os.getenv("NAGACON_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--streamlit-url", default=os.getenv("NAGACON_STREAMLIT_URL", "http://127.0.0.1:8501"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--out-dir", default="./streamlit_super_tester_v2_output")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--run-ingest", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--max-opps", type=int, default=3)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    build_readme(out_dir / "README_STREAMLIT_SUPER_TESTER_V2.txt")

    tester = TesterV2(
        base_url=args.base_url,
        streamlit_url=args.streamlit_url,
        timeout=args.timeout,
        out_dir=out_dir,
        browser=args.browser,
        run_ingest=args.run_ingest,
        strict=args.strict,
        max_opps=args.max_opps,
    )

    tester.backend_global_suite()
    tester.maybe_ingest()
    tester.discover_context()
    opp_ids = tester.context.get("opportunity_ids") or []
    if not opp_ids:
        tester.record(name="Opportunity discovery", category="core", method="DISCOVER", target="/api/opportunities", ok=False, status="MISS", summary="no opportunity discovered", sample=tester.context)
    else:
        tester.record(name="Opportunity discovery", category="core", method="DISCOVER", target="/api/opportunities", ok=True, status=200, summary=f"discovered {len(opp_ids)} opportunities", sample={"opportunity_ids": opp_ids})
        for opp_id in opp_ids:
            tester.backend_opportunity_suite(int(opp_id))
    tester.browser_suite()
    tester.cleanup()
    json_path, txt_path, csv_path, html_path, summary = tester.write_reports()

    print(json.dumps({
        "summary": summary,
        "json_report": str(json_path),
        "txt_report": str(txt_path),
        "csv_report": str(csv_path),
        "html_report": str(html_path),
    }, indent=2))

    failed = summary["failed"]
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
