from __future__ import annotations

from typing import Any

from api_client import get_json, post


def list_opportunities(limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    return get_json("/api/opportunities/", {"limit": limit, "offset": offset})


def get_opportunity(opportunity_id: int) -> dict[str, Any]:
    return get_json(f"/api/opportunities/{opportunity_id}")


def get_workspace(opportunity_id: int) -> dict[str, Any]:
    return get_json(f"/api/opportunities/{opportunity_id}/workspace")


def ingest_opportunities(raw_records: list[dict[str, Any]]) -> dict[str, Any]:
    return post("/api/opportunities/ingest", raw_records)


def run_sam_scraper(limit: int = 10, posted_from: str | None = None, posted_to: str | None = None, q: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"limit": limit}
    if posted_from:
        payload["postedFrom"] = posted_from
    if posted_to:
        payload["postedTo"] = posted_to
    if q:
        payload["q"] = q
    return post("/api/scrapers/sam/run", payload)


def run_dibbs_scraper(max_pages: int = 1, fsc: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"max_pages": max_pages}
    if fsc:
        payload["fsc"] = fsc
    return post("/api/scrapers/dibbs/run", payload)
