import requests

BASE_URL = "http://127.0.0.1:8000"


def generate_vendor_email(opportunity_id: int, vendor_quote_id: int | None = None, vendor_lead_id: int | None = None):
    params = {}
    if vendor_quote_id is not None:
        params["vendor_quote_id"] = vendor_quote_id
    if vendor_lead_id is not None:
        params["vendor_lead_id"] = vendor_lead_id

    r = requests.post(
        f"{BASE_URL}/api/vendor-email/opportunities/{opportunity_id}/draft",
        params=params,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()
