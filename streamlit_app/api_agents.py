from __future__ import annotations

from typing import Any

from api_client import post


def generate_proposal(opportunity_id: int) -> dict[str, Any]:
    return post(f"/api/agents/opportunities/{opportunity_id}/proposal-draft", {})


def orchestrate_agents(opportunity_id: int, agents: list[str]) -> dict[str, Any]:
    payload = {"opportunity_id": opportunity_id, "agents": agents}
    return post("/api/agents/orchestrate", payload)
