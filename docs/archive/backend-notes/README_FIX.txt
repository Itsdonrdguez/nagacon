This patch fixes the ImportError by restoring the full enrich_dibbs_batch implementation.

Replace these files:
- backend/app/api/dibbs_enrich.py
- backend/app/services/dibbs/structured_detail_parser.py
- backend/app/services/dibbs/detail_enrichment_playwright.py

Then restart:
uvicorn app.main:app --reload

Retest:
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/dibbs/enrich" -ContentType "application/json" -Body '{"limit":5,"source":"DIBBS","debug":true}' | ConvertTo-Json -Depth 10
