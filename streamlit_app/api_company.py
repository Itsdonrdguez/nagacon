from __future__ import annotations

from typing import Any

from api_client import get_json


def get_company_profile(profile_id: int = 1) -> dict[str, Any] | None:
    try:
        return get_json(f"/api/company/profile/{profile_id}")
    except Exception:
        try:
            return get_json("/api/company/profile")
        except Exception:
            return None


def list_past_performance(profile_id: int = 1) -> list[dict[str, Any]]:
    try:
        return get_json(f"/api/company/past-performance/{profile_id}")
    except Exception:
        return []
