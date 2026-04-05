
import requests

BASE_URL = "http://127.0.0.1:8000"

def usaspending_research(opportunity_id: int):
    r = requests.post(f"{BASE_URL}/api/research/usaspending/opportunities/{opportunity_id}", timeout=60)
    r.raise_for_status()
    return r.json()

def usaspending_seed_leads(opportunity_id: int):
    r = requests.post(f"{BASE_URL}/api/research/usaspending/opportunities/{opportunity_id}/seed-leads", timeout=60)
    r.raise_for_status()
    return r.json()
