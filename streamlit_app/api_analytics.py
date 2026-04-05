from __future__ import annotations

from typing import Any

from api_client import get_json


def get_analytics_summary() -> dict[str, Any]:
    return get_json("/api/analytics/summary")
