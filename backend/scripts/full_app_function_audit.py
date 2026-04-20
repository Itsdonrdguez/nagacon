from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from app.main import app
from app.core.db import SessionLocal
from app.services.app_settings_service import get_setting
from app.services.audit.function_audit import audit_routes, route_key
from app.services.org_service import ensure_default_organization


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "audit_reports" / "full_app_function_audit_latest.json"
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"SAM-[A-Za-z0-9_-]+"),
)


def http_call(method: str, url: str, *, api_key: str | None = None, timeout: int = 25) -> tuple[int | None, str, int]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = request.Request(url, method=method, headers=headers)
    started = time.time()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), round((time.time() - started) * 1000)
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), round((time.time() - started) * 1000)
    except Exception as exc:
        return None, str(exc), round((time.time() - started) * 1000)


def classify_result(status: int | None) -> str:
    if status is None:
        return "FAILED"
    if 200 <= status < 300:
        return "SUCCESS"
    if status >= 500:
        return "FAILED"
    return "REJECTED"


def redact(value: str) -> str:
    text = value or ""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(redact_payload(payload), separators=(",", ":"))


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if "key" in lowered or "secret" in lowered or "token" in lowered:
                if isinstance(item, list):
                    redacted[key] = ["[REDACTED]" for _ in item]
                elif item:
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = item
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def get_json(base_url: str, path: str, *, api_key: str | None = None) -> Any:
    status, text, _ = http_call("GET", f"{base_url}{path}", api_key=api_key)
    if not status or status >= 400:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def configured_integration_key(base_url: str) -> str | None:
    db = SessionLocal()
    try:
        org = ensure_default_organization(db)
        stored = get_setting(db, "external_api_keys", default="", organization_id=getattr(org, "id", None)) or ""
        keys = [item.strip() for item in stored.split(",") if item.strip()]
        return keys[0] if keys else None
    finally:
        db.close()


def collect_context(base_url: str, *, max_examples: int, api_key: str | None) -> dict[str, list[Any]]:
    context: dict[str, list[Any]] = {
        "opportunity_id": [],
        "provider_id": [],
        "profile_id": [],
        "pipeline_id": [],
        "file_id": [],
        "task_id": [],
        "artifact_id": [],
        "quote_id": [],
        "nsn": ["4110015342682"],
        "job_id": ["not-a-real-job"],
    }
    opportunities = get_json(base_url, f"/api/opportunities/search?page=1&page_size={max_examples}") or {}
    for item in (opportunities.get("items") or [])[:max_examples]:
        if item.get("id"):
            context["opportunity_id"].append(item["id"])
        digits = "".join(ch for ch in str(item.get("solicitation_number") or "") if ch.isdigit())
        if len(digits) == 13 and digits not in context["nsn"]:
            context["nsn"].append(digits)

    providers = get_json(base_url, f"/api/providers?limit={max_examples}") or {}
    for item in (providers.get("items") or [])[:max_examples]:
        if item.get("provider_id"):
            context["provider_id"].append(item["provider_id"])

    profile = get_json(base_url, "/api/company/profile")
    if isinstance(profile, dict) and profile.get("id"):
        context["profile_id"].append(profile["id"])

    board = get_json(base_url, "/api/pipeline/board") or {}
    for item in (board.get("items") or [])[:max_examples]:
        if item.get("id"):
            context["pipeline_id"].append(item["id"])

    for opp_id in context["opportunity_id"][:max_examples]:
        files = get_json(base_url, f"/api/files/list?opportunity_id={opp_id}") or []
        for item in files if isinstance(files, list) else []:
            if item.get("id") and item["id"] not in context["file_id"]:
                context["file_id"].append(item["id"])

        summary = get_json(base_url, f"/api/workspace/summary?opp_id={opp_id}") or {}
        for item in summary.get("tasks", []) if isinstance(summary, dict) else []:
            if item.get("id") and item["id"] not in context["task_id"]:
                context["task_id"].append(item["id"])
        for item in summary.get("artifacts", []) if isinstance(summary, dict) else []:
            if item.get("id") and item["id"] not in context["artifact_id"]:
                context["artifact_id"].append(item["id"])

        quotes = get_json(base_url, f"/api/quotes/opportunities/{opp_id}") or []
        for item in quotes if isinstance(quotes, list) else []:
            if item.get("id") and item["id"] not in context["quote_id"]:
                context["quote_id"].append(item["id"])

    for key, values in list(context.items()):
        context[key] = values[:max_examples]
    return context


def values_for_placeholder(name: str, context: dict[str, list[Any]], max_examples: int) -> list[Any]:
    if name == "opportunity_id":
        return context["opportunity_id"] or [0]
    if name == "opp_id":
        return context["opportunity_id"] or [0]
    if name == "provider_id":
        return context["provider_id"] or [0]
    if name == "profile_id":
        return context["profile_id"] or [0]
    if name == "pipeline_id":
        return context["pipeline_id"] or [0]
    if name == "file_id":
        return context["file_id"] or [0]
    if name == "artifact_id":
        return context["artifact_id"] or [0]
    if name == "quote_id":
        return context["quote_id"] or [0]
    if name == "task_id":
        return context["task_id"] or [0]
    if name == "job_id":
        return context["job_id"]
    if name == "nsn":
        return context["nsn"] or ["4110015342682"]
    if name in {"perf_id", "version_index"}:
        return [0]
    return [0]


def expand_path(path: str, context: dict[str, list[Any]], max_examples: int) -> list[str]:
    placeholders = [part[1:-1] for part in path.split("/") if part.startswith("{") and part.endswith("}")]
    if not placeholders:
        return [with_default_query(path, context)]

    expanded = [path]
    for placeholder in placeholders:
        values = values_for_placeholder(placeholder, context, max_examples)
        next_paths: list[str] = []
        for current in expanded:
            for value in values[:max_examples]:
                next_paths.append(current.replace(f"{{{placeholder}}}", parse.quote(str(value))))
        expanded = next_paths
    return [with_default_query(item, context) for item in expanded[:max_examples]]


def with_default_query(path: str, context: dict[str, list[Any]]) -> str:
    if "?" in path:
        return path
    if path == "/api/opportunities":
        return f"{path}?limit=10"
    if path == "/api/opportunities/search":
        return f"{path}?page=1&page_size=10"
    if path == "/api/providers":
        return f"{path}?limit=10"
    if path == "/api/files/list":
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opportunity_id={opp_id}"
    if path == "/api/workspace/summary":
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opp_id={opp_id}"
    if path in {"/api/workspace/tasks", "/api/workspace/vendors/usaspending", "/api/workspace/intelligence/nsn"}:
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opp_id={opp_id}"
    if path == "/api/vendors/quotes":
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opportunity_id={opp_id}"
    if path == "/api/vendors/leads":
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opportunity_id={opp_id}&limit=10"
    if path == "/api/submissions":
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opportunity_id={opp_id}"
    if path == "/api/integrations/opportunities/search":
        return f"{path}?page=1&page_size=10"
    if path == "/api/export/bid_package":
        opp_id = (context.get("opportunity_id") or [0])[0]
        return f"{path}?opportunity_id={opp_id}"
    return path


def run_audit(base_url: str, *, max_examples: int, api_key: str | None, timeout: int) -> dict[str, Any]:
    context = collect_context(base_url, max_examples=max_examples, api_key=api_key)
    rows = []
    for route in audit_routes(app):
        paths = expand_path(route.path, context, max_examples) if route.runnable_live else [route.path]
        for path in paths:
            if not route.runnable_live:
                rows.append(
                    {
                        "route": route_key(route),
                        "method": route.method,
                        "path": path,
                        "category": route.category,
                        "result": "SKIPPED",
                        "status": "SKIP",
                        "ms": 0,
                        "reason": route.reason,
                        "body": "",
                    }
                )
                break
            key = api_key if route.category == "protected_read" else None
            status, body, ms = http_call(route.method, f"{base_url}{path}", api_key=key, timeout=timeout)
            rows.append(
                {
                    "route": route_key(route),
                    "method": route.method,
                    "path": path,
                    "category": route.category,
                    "result": classify_result(status),
                    "status": status,
                    "ms": ms,
                    "reason": route.reason,
                    "body": redact(body or "").replace("\n", " ")[:300],
                }
            )

    summary: dict[str, int] = {}
    for row in rows:
        summary[row["result"]] = summary.get(row["result"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "max_examples": max_examples,
        "summary": summary,
        "context": context,
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a live, non-destructive audit of all FastAPI app functions.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-examples", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--use-configured-api-key", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    api_key = args.api_key
    if args.use_configured_api_key and not api_key:
        api_key = configured_integration_key(args.base_url)

    result = run_audit(
        args.base_url.rstrip("/"),
        max_examples=max(min(args.max_examples, 10), 1),
        api_key=api_key,
        timeout=args.timeout,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps({"summary": result["summary"], "output": str(output_path)}, indent=2))
    failures = [row for row in result["results"] if row["result"] == "FAILED"]
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
