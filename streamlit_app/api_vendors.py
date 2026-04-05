import os
import requests

API_BASE = os.getenv("NAGACON_API", "http://127.0.0.1:8000").rstrip("/")


def vendors_sync_leads(opportunity_id: int) -> dict:
    r = requests.post(f"{API_BASE}/api/vendors/leads/sync", json={"opportunity_id": opportunity_id}, timeout=120)
    r.raise_for_status()
    return r.json()


def vendors_get_leads(opportunity_id: int) -> list[dict]:
    r = requests.get(f"{API_BASE}/api/vendors/leads", params={"opportunity_id": opportunity_id}, timeout=60)
    r.raise_for_status()
    return r.json()


def vendors_upsert_lead(payload: dict) -> dict:
    r = requests.post(f"{API_BASE}/api/vendors/leads/upsert", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def vendors_seed(opportunity_id: int) -> dict:
    r = requests.post(f"{API_BASE}/api/vendors/quotes/seed", json={"opportunity_id": opportunity_id}, timeout=120)
    r.raise_for_status()
    return r.json()


def vendors_get_quotes(opportunity_id: int) -> list[dict]:
    r = requests.get(f"{API_BASE}/api/vendors/quotes", params={"opportunity_id": opportunity_id}, timeout=60)
    r.raise_for_status()
    return r.json()


def vendors_upsert_quote(payload: dict) -> dict:
    r = requests.post(f"{API_BASE}/api/vendors/quotes/upsert", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()
