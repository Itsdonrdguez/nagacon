from __future__ import annotations

from typing import Any

from api_client import post


def run_state_local_scraper(source: str, params: dict | None = None) -> dict[str, Any]:
    return post(f"/api/scrapers/state-local/{source}/run", params or {})


def run_all_state_local(params: dict | None = None) -> dict[str, Any]:
    return post("/api/scrapers/state-local/all/run", params or {})
