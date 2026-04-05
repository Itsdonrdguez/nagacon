
import requests

USASPENDING_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

def search_similar_awards(naics=None, agency=None, keywords=None, limit=50):
    filters = {
        "award_type_codes": ["A", "B", "C", "D"],
    }

    if naics:
        filters["naics_codes"] = [naics]

    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency}]

    if keywords:
        filters["keywords"] = [keywords]

    payload = {
        "filters": filters,
        "fields": [
            "Award ID",
            "Recipient Name",
            "Start Date",
            "Award Amount",
            "Awarding Agency"
        ],
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc"
    }

    r = requests.post(USASPENDING_SEARCH_URL, json=payload)
    r.raise_for_status()
    return r.json().get("results", [])
