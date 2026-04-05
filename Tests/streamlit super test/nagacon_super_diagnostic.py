
"""
NagaCon Super Diagnostic
------------------------
Usage:
    python nagacon_super_diagnostic.py

What it checks:
- Core API connectivity
- Mounted feature routes
- Optional feature routes
- Basic database-backed workflows
- Environment/config hints
- Backend process availability
- Streamlit availability
- Health-style summary report

Notes:
- This script is read-only except for safe POST probes that hit existing
  feature endpoints you are already using for diagnostics.
- It does not mutate records except endpoints that naturally generate drafts
  or research responses.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests

BASE_URL = os.getenv("NAGACON_BASE_URL", "http://127.0.0.1:8000")
STREAMLIT_URL = os.getenv("NAGACON_STREAMLIT_URL", "http://127.0.0.1:8501")
DEFAULT_OPPORTUNITY_ID = int(os.getenv("NAGACON_OPPORTUNITY_ID", "49"))
TIMEOUT = 30


@dataclass
class CheckResult:
    name: str
    method: str
    url: str
    status: str
    ok: bool
    category: str
    summary: str
    sample: Any


def safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        text = resp.text.strip()
        return text[:1200] if text else ""


def run_request(
    name: str,
    method: str,
    route: str,
    *,
    category: str,
    json_body: dict | None = None,
    params: dict | None = None,
    expected_statuses: tuple[int, ...] = (200,),
    summary_ok: str = "working",
    summary_fail: str = "failed",
) -> CheckResult:
    url = f"{BASE_URL}{route}"
    try:
        if method.upper() == "GET":
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        elif method.upper() == "POST":
            resp = requests.post(url, json=json_body, params=params, timeout=TIMEOUT)
        elif method.upper() == "PATCH":
            resp = requests.patch(url, json=json_body, params=params, timeout=TIMEOUT)
        elif method.upper() == "DELETE":
            resp = requests.delete(url, params=params, timeout=TIMEOUT)
        else:
            raise ValueError(f"Unsupported method: {method}")

        ok = resp.status_code in expected_statuses
        summary = summary_ok if ok else summary_fail
        return CheckResult(
            name=name,
            method=method.upper(),
            url=resp.url,
            status=str(resp.status_code),
            ok=ok,
            category=category,
            summary=summary,
            sample=safe_json(resp),
        )
    except Exception as exc:
        return CheckResult(
            name=name,
            method=method.upper(),
            url=url,
            status="ERROR",
            ok=False,
            category=category,
            summary=summary_fail,
            sample=f"{type(exc).__name__}: {exc}",
        )


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def read_env_candidates() -> dict[str, str]:
    candidates = [
        ".env",
        "backend/.env",
        ".env.local",
        "backend/.env.local",
    ]
    found: dict[str, str] = {}
    for rel in candidates:
        p = Path(rel)
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                found[rel] = text[:4000]
            except Exception as exc:
                found[rel] = f"Could not read: {exc}"
    return found


def env_hint_check() -> list[CheckResult]:
    results: list[CheckResult] = []
    env_files = read_env_candidates()
    keys_to_hint = [
        "DATABASE_URL",
        "SAM_API_KEY",
        "OPENAI_API_KEY",
        "NAGACON_BASE_URL",
    ]

    combined = "\n".join(env_files.values()) if env_files else ""
    for key in keys_to_hint:
        present = (key in os.environ) or (key in combined)
        results.append(
            CheckResult(
                name=f"Env hint: {key}",
                method="LOCAL",
                url="-",
                status="PRESENT" if present else "MISSING",
                ok=present if key == "DATABASE_URL" else True,
                category="environment",
                summary=("found" if present else "not found"),
                sample={"os_environ": key in os.environ, "env_file_hint": key in combined},
            )
        )
    return results


def filesystem_hint_check() -> list[CheckResult]:
    targets = [
        "app/main.py",
        "backend/app/main.py",
        "streamlit_app",
        "alembic",
        "alembic.ini",
        "backend/alembic.ini",
    ]
    out: list[CheckResult] = []
    for t in targets:
        p = Path(t)
        out.append(
            CheckResult(
                name=f"Path exists: {t}",
                method="LOCAL",
                url="-",
                status="YES" if p.exists() else "NO",
                ok=True,
                category="filesystem",
                summary="present" if p.exists() else "missing",
                sample=str(p.resolve()) if p.exists() else "",
            )
        )
    return out


def build_checks(opportunity_id: int) -> list[CheckResult]:
    checks: list[CheckResult] = []

    # Core
    checks.append(
        run_request(
            "Opportunities list",
            "GET",
            "/api/opportunities",
            params={"limit": 5, "offset": 0},
            category="core",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="not working",
        )
    )
    checks.append(
        run_request(
            "Opportunity detail",
            "GET",
            f"/api/opportunities/{opportunity_id}",
            category="core",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="not working",
        )
    )
    checks.append(
        run_request(
            "Workspace summary",
            "GET",
            "/api/workspace/summary",
            params={"opp_id": opportunity_id},
            category="workspace",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="workspace issue",
        )
    )

    # Vendor lead engine
    checks.append(
        run_request(
            "Vendor leads list",
            "GET",
            "/api/vendors/leads",
            params={"opportunity_id": opportunity_id},
            category="vendors",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="not working",
        )
    )
    checks.append(
        run_request(
            "Vendor leads sync",
            "POST",
            "/api/vendors/leads/sync",
            json_body={"opportunity_id": opportunity_id},
            category="vendors",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="sync failed",
        )
    )
    checks.append(
        run_request(
            "Vendor discovery route",
            "POST",
            f"/api/vendor-discovery/opportunities/{opportunity_id}",
            category="vendors",
            expected_statuses=(200, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )

    # Proposal + vendor email
    checks.append(
        run_request(
            "Proposal assist draft",
            "POST",
            f"/api/proposal-assist/opportunities/{opportunity_id}/draft",
            category="proposal",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="not working",
        )
    )
    checks.append(
        run_request(
            "Vendor email generic draft",
            "POST",
            f"/api/vendor-email/opportunities/{opportunity_id}/draft",
            category="proposal",
            expected_statuses=(200,),
            summary_ok="mounted and working",
            summary_fail="not working",
        )
    )

    # Research
    checks.append(
        run_request(
            "USAspending research",
            "POST",
            f"/api/research/usaspending/opportunities/{opportunity_id}",
            category="research",
            expected_statuses=(200, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )

    # Scrapers
    checks.append(
        run_request(
            "SAM scraper",
            "POST",
            "/api/scrapers/sam/run",
            json_body={"limit": 3},
            category="scrapers",
            expected_statuses=(200, 400, 401, 403, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "DIBBS scraper",
            "POST",
            "/api/scrapers/dibbs/run",
            json_body={"fsc": "6515", "limit": 3},
            category="scrapers",
            expected_statuses=(200, 400, 404, 500, 502),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "State/local all",
            "POST",
            "/api/scrapers/state-local/all/run",
            category="scrapers",
            expected_statuses=(200, 400, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )

    # Optional routes from app/api/routes
    checks.append(
        run_request(
            "Pipeline get",
            "GET",
            "/api/pipeline/1",
            category="optional",
            expected_statuses=(200, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "Quotes list",
            "GET",
            f"/api/quotes/opportunities/{opportunity_id}",
            category="optional",
            expected_statuses=(200, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "Company profile",
            "GET",
            "/api/company/profile/1",
            category="optional",
            expected_statuses=(200, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "Analytics summary",
            "GET",
            "/api/analytics/summary",
            category="optional",
            expected_statuses=(200, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )

    # Existing file/workspace helpers
    checks.append(
        run_request(
            "Files list legacy",
            "GET",
            "/api/files/list",
            params={"opportunity_id": opportunity_id},
            category="files",
            expected_statuses=(200, 400, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "Workspace artifacts",
            "GET",
            "/api/workspace/artifacts",
            params={"opp_id": opportunity_id},
            category="workspace",
            expected_statuses=(200, 400, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )
    checks.append(
        run_request(
            "Workspace tasks",
            "GET",
            "/api/workspace/tasks",
            params={"opp_id": opportunity_id},
            category="workspace",
            expected_statuses=(200, 400, 404, 500),
            summary_ok="reachable",
            summary_fail="not reachable",
        )
    )

    return checks


def streamlit_check() -> CheckResult:
    url = STREAMLIT_URL
    try:
        resp = requests.get(url, timeout=10)
        return CheckResult(
            name="Streamlit UI",
            method="GET",
            url=url,
            status=str(resp.status_code),
            ok=resp.status_code < 400,
            category="ui",
            summary="reachable" if resp.status_code < 400 else "not reachable",
            sample=safe_json(resp),
        )
    except Exception as exc:
        return CheckResult(
            name="Streamlit UI",
            method="GET",
            url=url,
            status="ERROR",
            ok=False,
            category="ui",
            summary="not reachable",
            sample=f"{type(exc).__name__}: {exc}",
        )


def port_checks() -> list[CheckResult]:
    return [
        CheckResult(
            name="Backend port 8000",
            method="TCP",
            url="127.0.0.1:8000",
            status="OPEN" if port_open("127.0.0.1", 8000) else "CLOSED",
            ok=port_open("127.0.0.1", 8000),
            category="network",
            summary="reachable" if port_open("127.0.0.1", 8000) else "not reachable",
            sample="",
        ),
        CheckResult(
            name="Streamlit port 8501",
            method="TCP",
            url="127.0.0.1:8501",
            status="OPEN" if port_open("127.0.0.1", 8501) else "CLOSED",
            ok=True,
            category="network",
            summary="reachable" if port_open("127.0.0.1", 8501) else "not reachable",
            sample="",
        ),
    ]


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = total - passed

    by_category: dict[str, dict[str, int]] = {}
    for r in results:
        by_category.setdefault(r.category, {"passed": 0, "failed": 0})
        if r.ok:
            by_category[r.category]["passed"] += 1
        else:
            by_category[r.category]["failed"] += 1

    return {
        "base_url": BASE_URL,
        "streamlit_url": STREAMLIT_URL,
        "opportunity_id": DEFAULT_OPPORTUNITY_ID,
        "total_checks": total,
        "passed": passed,
        "failed": failed,
        "by_category": by_category,
    }


def save_report(results: list[CheckResult]) -> tuple[Path, Path]:
    json_path = Path("nagacon_super_diagnostic_report.json")
    txt_path = Path("nagacon_super_diagnostic_report.txt")

    payload = {
        "summary": summarize(results),
        "results": [asdict(r) for r in results],
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    lines: list[str] = []
    lines.append("NagaCon Super Diagnostic Report")
    lines.append("=" * 80)
    lines.append(json.dumps(payload["summary"], indent=2))
    lines.append("")
    for r in results:
        lines.append(f"{r.name}")
        lines.append(f"  METHOD: {r.method}")
        lines.append(f"  URL: {r.url}")
        lines.append(f"  STATUS: {r.status}")
        lines.append(f"  OK: {r.ok}")
        lines.append(f"  CATEGORY: {r.category}")
        lines.append(f"  SUMMARY: {r.summary}")
        try:
            sample = json.dumps(r.sample, indent=2, default=str)
        except Exception:
            sample = str(r.sample)
        lines.append("  SAMPLE:")
        for line in sample.splitlines():
            lines.append(f"    {line}")
        lines.append("-" * 80)
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    return json_path, txt_path


def main() -> int:
    results: list[CheckResult] = []
    try:
        results.extend(port_checks())
        results.extend(env_hint_check())
        results.extend(filesystem_hint_check())
        results.append(streamlit_check())
        results.extend(build_checks(DEFAULT_OPPORTUNITY_ID))
    except Exception as exc:
        print("FATAL ERROR while building diagnostics:")
        print(exc)
        traceback.print_exc()
        return 1

    summary = summarize(results)
    json_path, txt_path = save_report(results)

    print("\n" + "=" * 80)
    print("NAGACON SUPER DIAGNOSTIC")
    print("=" * 80)
    print(json.dumps(summary, indent=2))
    print("")
    for r in results:
        print(f"{r.name}")
        print(f"  {r.method} {r.url}")
        print(f"  STATUS: {r.status} | OK: {r.ok} | CATEGORY: {r.category}")
        print(f"  SUMMARY: {r.summary}")
        print("-" * 80)

    print(f"\nSaved JSON report to: {json_path.resolve()}")
    print(f"Saved text report to: {txt_path.resolve()}")

    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
