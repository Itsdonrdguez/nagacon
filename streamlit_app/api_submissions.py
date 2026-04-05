import os
import requests

API_BASE = os.getenv("NAGACON_API", "http://127.0.0.1:8000").rstrip("/")


def submission_get(opportunity_id: int) -> dict | None:
    r = requests.get(f"{API_BASE}/api/submissions", params={"opportunity_id": opportunity_id}, timeout=60)
    r.raise_for_status()
    return r.json()


def submission_upsert(payload: dict) -> dict:
    r = requests.post(f"{API_BASE}/api/submissions/upsert", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()
