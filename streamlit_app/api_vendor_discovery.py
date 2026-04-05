from __future__ import annotations

from typing import Any

from api_client import post


def discover_workspace_vendors(opportunity_id: int) -> dict[str, Any]:
    return post(f"/api/vendor-discovery/opportunities/{opportunity_id}", {})
