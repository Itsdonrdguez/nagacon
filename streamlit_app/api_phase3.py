import requests

BASE_URL = "http://127.0.0.1:8000"


def create_suggested_quote(opportunity_id: int, vendor_lead_id: int, markup_pct: float = 12.0, unit_cost: float = 0.0):
    r = requests.post(
        f"{BASE_URL}/api/phase3/opportunities/{opportunity_id}/suggested-quote",
        params={
            "vendor_lead_id": vendor_lead_id,
            "markup_pct": markup_pct,
            "unit_cost": unit_cost,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()
