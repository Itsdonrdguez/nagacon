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


class Tester:
    def __init__(self, base_url: str, streamlit_url: str, timeout: int, out_dir: Path, browser: bool, run_ingest: bool):
        self.base_url = base_url.rstrip("/")
        self.streamlit_url = streamlit_url.rstrip("/")
        self.timeout = timeout
        self.out_dir = out_dir
        self.browser = browser
        self.run_ingest = run_ingest
        self.session = requests.Session()
        self.results: list[TestResult] = []
        self.context: dict[str, Any] = {
            "opportunity_id": None,
            "pipeline_id": None,
            "file_id": None,
            "vendor_lead_id": None,
            "vendor_quote_id": None,
            "task_id": None,
        }
        self.created_quotes: list[int] = []

    def record(self, **kwargs):
        self.results.append(TestResult(**kwargs))

    def _request(self, method: str, path: str, *, json_body: Any = None, expected: Iterable[int] = (200,), allow_redirects: bool = True) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        return self.session.request(
            method=method,
            url=url,
            json=json_body,
            timeout=self.timeout,
            allow_redirects=allow_redirects,
        )

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

    @staticmethod
    def _json_or_text(resp: requests.Response):
        try:
            return resp.json()
        except Exception:
            return resp.text[:2000]

    def http_check(self, method: str, path: str, *, json_body: Any = None, expected: Iterable[int] = (200,)):
        resp = self._request(method, path, json_body=json_body)
        payload = self._json_or_text(resp)
        return {
            "ok": resp.status_code in set(expected),
            "status": resp.status_code,
            "summary": "ok" if resp.status_code in set(expected) else f"unexpected status {resp.status_code}",
            "sample": payload,
        }

    def discover_context(self):
        # Opportunity list
        resp = self._request("GET", "/api/opportunities?limit=25&offset=0")
        payload = self._json_or_text(resp)
        if resp.status_code == 200 and isinstance(payload, list) and payload:
            opp = payload[0]
            self.context["opportunity_id"] = opp.get("id")
        # Pipeline
        if self.context["opportunity_id"]:
            opp_id = self.context["opportunity_id"]
            presp = self._request("GET", f"/api/pipeline/by-opportunity/{opp_id}")
            if presp.status_code == 200:
                pdata = self._json_or_text(presp)
                if isinstance(pdata, dict):
                    self.context["pipeline_id"] = pdata.get("id")
            # files
            fresp = self._request("GET", f"/api/files/list?opportunity_id={opp_id}")
            if fresp.status_code == 200:
                fdata = self._json_or_text(fresp)
                if isinstance(fdata, list) and fdata:
                    self.context["file_id"] = fdata[0].get("id")
            # leads
            lresp = self._request("GET", f"/api/vendors/leads?opportunity_id={opp_id}")
            if lresp.status_code == 200:
                ldata = self._json_or_text(lresp)
                if isinstance(ldata, list) and ldata:
                    self.context["vendor_lead_id"] = ldata[0].get("id")
            # quotes
            qresp = self._request("GET", f"/api/vendors/quotes?opportunity_id={opp_id}")
            if qresp.status_code == 200:
                qdata = self._json_or_text(qresp)
                if isinstance(qdata, list) and qdata:
                    self.context["vendor_quote_id"] = qdata[0].get("id")

    def maybe_ingest(self):
        if not self.run_ingest:
            return
        self.run_test(
            name="Ingest DIBBS",
            category="ingest",
            method="POST",
            target="/api/scrapers/dibbs/run",
            fn=lambda: self.http_check("POST", "/api/scrapers/dibbs/run", json_body={"max_pages": 1, "fsc": "6520", "limit": 5}, expected=(200,)),
        )
        # Try SAM only if key present on machine; route may still work with graceful error
        self.run_test(
            name="Ingest SAM",
            category="ingest",
            method="POST",
            target="/api/scrapers/sam/run",
            fn=lambda: self.http_check("POST", "/api/scrapers/sam/run", json_body={"limit": 5, "q": "medical", "debug": True}, expected=(200, 400, 401, 422, 500)),
        )
        self.discover_context()

    def backend_suite(self):
        self.run_test("Health", "core", "GET", "/api/health/", lambda: self.http_check("GET", "/api/health/"))
        self.run_test("Opportunities list", "core", "GET", "/api/opportunities", lambda: self.http_check("GET", "/api/opportunities?limit=10&offset=0"))
        opp_id = self.context.get("opportunity_id")
        if not opp_id:
            return
        self.run_test("Opportunity detail", "core", "GET", f"/api/opportunities/{opp_id}", lambda: self.http_check("GET", f"/api/opportunities/{opp_id}"))
        self.run_test("Workspace summary", "workspace", "GET", f"/api/workspace/summary?opp_id={opp_id}", lambda: self.http_check("GET", f"/api/workspace/summary?opp_id={opp_id}"))
        self.run_test("Workspace parse", "workspace", "POST", "/api/workspace/parse", lambda: self.http_check("POST", "/api/workspace/parse", json_body={"opportunity_id": opp_id}))
        self.run_test("Generate checklist", "workspace", "POST", "/api/workspace/generate/checklist", lambda: self.http_check("POST", "/api/workspace/generate/checklist", json_body={"opportunity_id": opp_id}))
        self.run_test("Generate vendors", "workspace", "POST", "/api/workspace/generate/vendors", lambda: self.http_check("POST", "/api/workspace/generate/vendors", json_body={"opportunity_id": opp_id}))
        self.run_test("Generate email", "workspace", "POST", "/api/workspace/generate/email", lambda: self.http_check("POST", "/api/workspace/generate/email", json_body={"opportunity_id": opp_id}))
        self.run_test("List artifacts", "workspace", "GET", "/api/workspace/artifacts", lambda: self.http_check("GET", f"/api/workspace/artifacts?opportunity_id={opp_id}"))

        def create_task():
            resp = self._request("POST", "/api/workspace/tasks", json_body={"opportunity_id": opp_id, "title": f"Streamlit super tester {datetime.utcnow().strftime('%H%M%S')}"})
            payload = self._json_or_text(resp)
            if resp.status_code == 200 and isinstance(payload, dict):
                self.context["task_id"] = payload.get("id")
            return {"ok": resp.status_code == 200, "status": resp.status_code, "summary": "ok" if resp.status_code == 200 else "failed", "sample": payload}
        self.run_test("Create task", "workspace", "POST", "/api/workspace/tasks", create_task)
        self.run_test("List tasks", "workspace", "GET", "/api/workspace/tasks", lambda: self.http_check("GET", f"/api/workspace/tasks?opportunity_id={opp_id}"))
        self.run_test("Export ZIP", "workspace", "GET", "/api/workspace/export.zip", lambda: self.http_check("GET", f"/api/workspace/export.zip?opportunity_id={opp_id}"))

        self.run_test("Files list", "files", "GET", "/api/files/list", lambda: self.http_check("GET", f"/api/files/list?opportunity_id={opp_id}"))
        self.run_test("Download PDFs", "files", "POST", "/api/files/download_pdfs", lambda: self.http_check("POST", "/api/files/download_pdfs", json_body={"opportunity_id": opp_id}))
        file_id = self.context.get("file_id")
        if file_id:
            self.run_test("Parse file", "files", "POST", f"/api/files/parse/{file_id}", lambda: self.http_check("POST", f"/api/files/parse/{file_id}", expected=(200, 404)))
            self.run_test("Download file", "files", "GET", f"/api/files/download/{file_id}", lambda: self.http_check("GET", f"/api/files/download/{file_id}", expected=(200, 302, 307)))

        self.run_test("Pipeline get by opportunity", "pipeline", "GET", f"/api/pipeline/by-opportunity/{opp_id}", lambda: self.http_check("GET", f"/api/pipeline/by-opportunity/{opp_id}", expected=(200, 404)))

        def ensure_pipeline():
            resp = self._request("POST", f"/api/pipeline/by-opportunity/{opp_id}", json_body={})
            payload = self._json_or_text(resp)
            if resp.status_code == 200 and isinstance(payload, dict):
                self.context["pipeline_id"] = payload.get("id")
            return {"ok": resp.status_code == 200, "status": resp.status_code, "summary": "ok" if resp.status_code == 200 else "failed", "sample": payload}
        self.run_test("Pipeline create or get", "pipeline", "POST", f"/api/pipeline/by-opportunity/{opp_id}", ensure_pipeline)

        pipeline_id = self.context.get("pipeline_id")
        if pipeline_id:
            self.run_test(
                "Pipeline patch",
                "pipeline",
                "PATCH",
                f"/api/pipeline/{pipeline_id}",
                lambda: self.http_check("PATCH", f"/api/pipeline/{pipeline_id}", json_body={"owner": "streamlit-super-tester", "priority": "High", "notes": "Updated by automated tester"}),
            )

        self.run_test("Vendor leads list", "vendors", "GET", "/api/vendors/leads", lambda: self.http_check("GET", f"/api/vendors/leads?opportunity_id={opp_id}"))
        self.run_test("Vendor leads sync", "vendors", "POST", "/api/vendors/leads/sync", lambda: self.http_check("POST", "/api/vendors/leads/sync", json_body={"opportunity_id": opp_id}))
        self.run_test("Vendor discovery", "vendors", "POST", f"/api/vendor-discovery/opportunities/{opp_id}", lambda: self.http_check("POST", f"/api/vendor-discovery/opportunities/{opp_id}", expected=(200, 500)))
        self.run_test("Vendor email draft", "vendors", "POST", f"/api/vendor-email/opportunities/{opp_id}/draft", lambda: self.http_check("POST", f"/api/vendor-email/opportunities/{opp_id}/draft", json_body={"opportunity_id": opp_id}, expected=(200, 400, 404)))

        self.run_test("Vendor quotes list", "quotes", "GET", "/api/vendors/quotes", lambda: self.http_check("GET", f"/api/vendors/quotes?opportunity_id={opp_id}"))
        self.run_test("Seed quotes", "quotes", "POST", "/api/vendors/quotes/seed", lambda: self.http_check("POST", "/api/vendors/quotes/seed", json_body={"opportunity_id": opp_id}))

        def create_temp_quote():
            payload = {
                "opportunity_id": opp_id,
                "company_name": "TEST VENDOR",
                "part_number": f"TEST-{datetime.utcnow().strftime('%H%M%S')}",
                "status": "NOT_REQUESTED",
            }
            resp = self._request("POST", "/api/quotes/", json_body=payload)
            data = self._json_or_text(resp)
            if resp.status_code == 200 and isinstance(data, dict) and data.get("id"):
                self.created_quotes.append(int(data["id"]))
                self.context["vendor_quote_id"] = int(data["id"])
            return {"ok": resp.status_code == 200, "status": resp.status_code, "summary": "ok" if resp.status_code == 200 else "failed", "sample": data}
        self.run_test("Create temp quote", "quotes", "POST", "/api/quotes/", create_temp_quote)

        quote_id = self.context.get("vendor_quote_id")
        if quote_id:
            self.run_test("Patch quote", "quotes", "PATCH", f"/api/quotes/{quote_id}", lambda: self.http_check("PATCH", f"/api/quotes/{quote_id}", json_body={"status": "REQUESTED", "notes": "Patched by tester"}, expected=(200, 422)))

        self.run_test("Suggested quote", "quotes", "POST", f"/api/phase3/opportunities/{opp_id}/suggested-quote", lambda: self.http_check("POST", f"/api/phase3/opportunities/{opp_id}/suggested-quote", expected=(200, 400, 404, 500)))
        self.run_test("Proposal assist", "proposal", "POST", f"/api/proposal-assist/opportunities/{opp_id}/draft", lambda: self.http_check("POST", f"/api/proposal-assist/opportunities/{opp_id}/draft", expected=(200, 400, 404)))
        self.run_test("Research USAspending", "research", "POST", f"/api/research/usaspending/opportunities/{opp_id}", lambda: self.http_check("POST", f"/api/research/usaspending/opportunities/{opp_id}", expected=(200, 400, 404, 500)))
        self.run_test("Seed research leads", "research", "POST", f"/api/research/usaspending/opportunities/{opp_id}/seed-leads", lambda: self.http_check("POST", f"/api/research/usaspending/opportunities/{opp_id}/seed-leads", expected=(200, 400, 404, 500)))
        self.run_test("Analytics summary", "analytics", "GET", "/api/analytics/summary", lambda: self.http_check("GET", "/api/analytics/summary"))
        self.run_test("Predecessor research", "research", "GET", f"/api/research/predecessor/opportunities/{opp_id}", lambda: self.http_check("GET", f"/api/research/predecessor/opportunities/{opp_id}", expected=(200, 404, 500)))

    def streamlit_http_suite(self):
        def check_url(name: str, url: str):
            self.run_test(name, "streamlit-http", "GET", url, lambda: self._streamlit_get(url))

        check_url("Streamlit root", self.streamlit_url)
        for suffix in ["/Opportunities", "/Workspace?opp_id=%s" % (self.context.get("opportunity_id") or 1), "/System_Status"]:
            check_url(f"Streamlit page {suffix}", f"{self.streamlit_url}{suffix}")

    def _streamlit_get(self, url: str):
        resp = self.session.get(url, timeout=self.timeout)
        text = resp.text[:2000]
        ok = resp.status_code == 200 and ("streamlit" in text.lower() or "<!doctype html" in text.lower() or "<html" in text.lower())
        return {"ok": ok, "status": resp.status_code, "summary": "reachable" if ok else "not reachable", "sample": text}

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
            safe = name.lower().replace(" ", "_").replace("/", "_")
            path = screenshots_dir / f"{safe}.png"
            page.screenshot(path=str(path), full_page=True)
            return str(path)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1200})
                for page_name, url in [
                    ("home", self.streamlit_url),
                    ("opportunities", f"{self.streamlit_url}/Opportunities"),
                    ("workspace", f"{self.streamlit_url}/Workspace?opp_id={self.context.get('opportunity_id') or 1}"),
                    ("system_status", f"{self.streamlit_url}/System_Status"),
                ]:
                    start = time.time()
                    try:
                        page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
                        page.wait_for_timeout(1500)
                        content = page.content()[:2000]
                        screenshot = snap(page, page_name)
                        ok = len(content) > 0
                        self.record(name=f"Browser {page_name}", category="streamlit-browser", method="BROWSER", target=url, ok=ok, status=200 if ok else "ERR", summary="loaded", sample={"screenshot": screenshot, "content_head": content}, elapsed_ms=int((time.time() - start) * 1000))
                    except Exception as e:
                        self.record(name=f"Browser {page_name}", category="streamlit-browser", method="BROWSER", target=url, ok=False, status="ERR", summary=str(e), sample=None, elapsed_ms=int((time.time() - start) * 1000))

                # Deeper workspace actions if visible
                try:
                    page.goto(f"{self.streamlit_url}/Workspace?opp_id={self.context.get('opportunity_id') or 1}", wait_until="networkidle", timeout=self.timeout * 1000)
                    page.wait_for_timeout(1500)
                    for label in ["Refresh Workspace", "Generate Checklist", "Generate Vendor Shortlist", "Generate Quote Email", "Build Export ZIP"]:
                        start = time.time()
                        try:
                            locator = page.get_by_role("button", name=label)
                            if locator.count() > 0:
                                locator.first.click(timeout=3000)
                                page.wait_for_timeout(1500)
                                screenshot = snap(page, f"workspace_{label}")
                                self.record(name=f"Browser click {label}", category="streamlit-browser", method="BROWSER", target=label, ok=True, status=200, summary="clicked", sample={"screenshot": screenshot}, elapsed_ms=int((time.time()-start)*1000))
                            else:
                                self.record(name=f"Browser click {label}", category="streamlit-browser", method="BROWSER", target=label, ok=False, status="MISS", summary="button not found", sample=None, elapsed_ms=int((time.time()-start)*1000))
                        except Exception as e:
                            self.record(name=f"Browser click {label}", category="streamlit-browser", method="BROWSER", target=label, ok=False, status="ERR", summary=str(e), sample=None, elapsed_ms=int((time.time()-start)*1000))
                finally:
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

        json_path = self.out_dir / f"streamlit_super_tester_report_{timestamp}.json"
        txt_path = self.out_dir / f"streamlit_super_tester_report_{timestamp}.txt"
        csv_path = self.out_dir / f"streamlit_super_tester_report_{timestamp}.csv"

        payload = {"summary": summary, "results": [dataclasses.asdict(r) for r in self.results]}
        json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "category", "method", "target", "ok", "status", "summary", "elapsed_ms"])
            writer.writeheader()
            for r in self.results:
                writer.writerow({k: getattr(r, k) for k in ["name", "category", "method", "target", "ok", "status", "summary", "elapsed_ms"]})

        lines = [
            "NagaCon Streamlit Super Tester",
            "=" * 80,
            json.dumps(summary, indent=2),
            "",
        ]
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
                f"  SAMPLE: {textwrap.shorten(json.dumps(r.sample, default=str), width=1200, placeholder=' ...') if r.sample is not None else ''}",
                "-" * 80,
            ])
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, txt_path, csv_path, summary


def build_readme(path: Path):
    text = """\
NagaCon Streamlit Super Tester
==============================

What it does
------------
- Tests backend API health and core routes.
- Can trigger ingestion for DIBBS and SAM.
- Discovers a real opportunity automatically.
- Exercises workspace flows end-to-end: parse, checklist, vendor shortlist, email draft, tasks, export.
- Tests files routes, pipeline routes, vendor routes, quote routes, proposal assist, analytics, and research routes.
- Tests Streamlit over HTTP.
- Optionally runs browser automation with Playwright and saves screenshots.
- Writes JSON, CSV, and TXT reports automatically.

How to run
----------
python streamlit_super_tester.py --base-url http://127.0.0.1:8000 --streamlit-url http://127.0.0.1:8501 --run-ingest --browser

Safer run without browser
-------------------------
python streamlit_super_tester.py --base-url http://127.0.0.1:8000 --streamlit-url http://127.0.0.1:8501 --run-ingest

Notes
-----
- Browser mode requires Playwright and Chromium installed.
- The script may create a temporary task and temporary quote for deep testing. It attempts to delete the temporary quote afterward.
- SAM tests can return an auth or env-related error if SAM_API_KEY is not configured.
"""
    path.write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Extremely powerful end-to-end tester for NagaCon Streamlit + backend")
    parser.add_argument("--base-url", default=os.getenv("NAGACON_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--streamlit-url", default=os.getenv("NAGACON_STREAMLIT_URL", "http://127.0.0.1:8501"))
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--out-dir", default="./streamlit_super_tester_output")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--run-ingest", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    build_readme(out_dir / "README_STREAMLIT_SUPER_TESTER.txt")

    tester = Tester(args.base_url, args.streamlit_url, args.timeout, out_dir, args.browser, args.run_ingest)
    tester.run_test("Backend root reachability", "network", "GET", args.base_url, lambda: tester._streamlit_get(args.base_url.replace(":8000", ":8000/api/health/")))
    tester.run_test("Streamlit reachability", "network", "GET", args.streamlit_url, lambda: tester._streamlit_get(args.streamlit_url))
    tester.maybe_ingest()
    tester.discover_context()
    tester.backend_suite()
    tester.streamlit_http_suite()
    tester.browser_suite()
    tester.cleanup()
    json_path, txt_path, csv_path, summary = tester.write_reports()

    print(json.dumps({
        "summary": summary,
        "json_report": str(json_path),
        "txt_report": str(txt_path),
        "csv_report": str(csv_path),
    }, indent=2))

    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
