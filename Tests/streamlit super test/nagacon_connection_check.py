
import requests
from pprint import pprint

BASE = "http://127.0.0.1:8000"

tests = [
    ("Opportunities list", "GET", "/api/opportunities?limit=5&offset=0"),
    ("Opportunity detail", "GET", "/api/opportunities/49"),
    ("Workspace summary", "GET", "/api/workspace/summary?opp_id=49"),
    ("Vendor leads", "GET", "/api/vendors/leads?opportunity_id=49"),
    ("Proposal draft", "POST", "/api/proposal-assist/opportunities/49/draft"),
    ("Vendor email draft", "POST", "/api/vendor-email/opportunities/49/draft"),
    ("USAspending research", "POST", "/api/research/usaspending/opportunities/49"),
]

results = []

for name, method, route in tests:
    url = BASE + route
    try:
        if method == "GET":
            r = requests.get(url)
        else:
            r = requests.post(url)
        status = r.status_code
        ok = status < 400
        try:
            data = r.json()
        except:
            data = r.text[:200]

    except Exception as e:
        status = "ERROR"
        ok = False
        data = str(e)

    results.append({
        "name": name,
        "method": method,
        "url": url,
        "status": status,
        "ok": ok,
        "sample": data
    })

print("\n===== NAGACON CONNECTION CHECK =====\n")

for r in results:
    print(f"{r['name']}")
    print(f"  {r['method']} {r['url']}")
    print(f"  STATUS: {r['status']} | OK: {r['ok']}")
    print("  SAMPLE RESPONSE:")
    pprint(r["sample"])
    print("-" * 60)
