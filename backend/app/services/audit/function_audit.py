from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_ONLY_MUTATING_LOOKING_GETS = {
    "/api/export/bid_package",
}

AI_OR_GENERATION_MARKERS = (
    "/agents/",
    "/proposal",
    "/vendor-email",
    "/generate/",
    "/scoring/",
    "/phase3/",
)

EXTERNAL_OR_LONG_RUNNING_MARKERS = (
    "/scrapers/",
    "/dibbs/",
    "/search-jobs",
    "/usaspending",
    "/vendor-discovery",
    "/discover",
    "/enrich",
    "/download_pdfs",
    "/import-publog",
    "/build",
    "/refresh",
    "/intake/run",
)

DESTRUCTIVE_MARKERS = (
    "/cleanup",
    "delete",
    "/suppress",
)


@dataclass(frozen=True)
class AuditRoute:
    name: str
    method: str
    path: str
    category: str
    runnable_live: bool
    reason: str


def api_routes(app: Any) -> list[tuple[str, str, str]]:
    routes: list[tuple[str, str, str]] = []
    for route in getattr(app, "routes", []):
        path = str(getattr(route, "path", ""))
        methods = getattr(route, "methods", None)
        if not path.startswith("/api") or not methods:
            continue
        for method in sorted(set(methods) - {"HEAD", "OPTIONS"}):
            routes.append((method, path, getattr(route, "name", "")))
    return sorted(routes, key=lambda item: (item[1], item[0], item[2]))


def classify_route(method: str, path: str, name: str = "") -> AuditRoute:
    normalized_method = method.upper()
    lowered = f"{path} {name}".lower()

    if path in READ_ONLY_MUTATING_LOOKING_GETS:
        return AuditRoute(
            name=name,
            method=normalized_method,
            path=path,
            category="file_export",
            runnable_live=False,
            reason="Can generate a file response and requires a known packaged opportunity.",
        )

    if normalized_method == "DELETE" or any(marker in lowered for marker in DESTRUCTIVE_MARKERS):
        return AuditRoute(
            name=name,
            method=normalized_method,
            path=path,
            category="destructive",
            runnable_live=False,
            reason="Deletes, cleans, or suppresses records.",
        )

    if any(marker in lowered for marker in AI_OR_GENERATION_MARKERS):
        return AuditRoute(
            name=name,
            method=normalized_method,
            path=path,
            category="ai_or_generation",
            runnable_live=False,
            reason="Can invoke AI, generate artifacts, or create suggested work product.",
        )

    if normalized_method == "GET":
        if path.startswith("/api/integrations"):
            return AuditRoute(
                name=name,
                method=normalized_method,
                path=path,
                category="protected_read",
                runnable_live=True,
                reason="Read-only integration endpoint; requires X-API-Key.",
            )
        return AuditRoute(
            name=name,
            method=normalized_method,
            path=path,
            category="read",
            runnable_live=True,
            reason="Read-only endpoint.",
        )

    if any(marker in lowered for marker in EXTERNAL_OR_LONG_RUNNING_MARKERS):
        return AuditRoute(
            name=name,
            method=normalized_method,
            path=path,
            category="external_or_long_running",
            runnable_live=False,
            reason="Can call external systems, parse/download files, or run background enrichment.",
        )

    if normalized_method in {"POST", "PATCH", "PUT"}:
        return AuditRoute(
            name=name,
            method=normalized_method,
            path=path,
            category="mutation",
            runnable_live=False,
            reason="Creates or updates application data.",
        )

    return AuditRoute(
        name=name,
        method=normalized_method,
        path=path,
        category="uncategorized",
        runnable_live=False,
        reason="No audit classification rule matched this route.",
    )


def audit_routes(app: Any) -> list[AuditRoute]:
    return [classify_route(method, path, name) for method, path, name in api_routes(app)]


def route_key(route: AuditRoute) -> str:
    return f"{route.method} {route.path} :: {route.name}"
