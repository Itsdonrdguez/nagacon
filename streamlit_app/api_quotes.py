from __future__ import annotations

from typing import Any

from api_client import delete_json, get_json, patch_json, post


def list_quotes(opportunity_id: int) -> list[dict[str, Any]]:
    return get_json(f"/api/quotes/opportunities/{opportunity_id}")


def create_quote(payload: dict[str, Any]) -> dict[str, Any]:
    return post("/api/quotes/", payload)


def update_quote(quote_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    return patch_json(f"/api/quotes/{quote_id}", payload)


def delete_quote(quote_id: int) -> dict[str, Any]:
    return delete_json(f"/api/quotes/{quote_id}")
