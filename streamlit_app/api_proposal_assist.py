import requests

BASE_URL = "http://127.0.0.1:8000"


def generate_proposal_draft(opportunity_id: int):
    r = requests.post(f"{BASE_URL}/api/proposal-assist/opportunities/{opportunity_id}/draft", timeout=60)
    r.raise_for_status()
    return r.json()
