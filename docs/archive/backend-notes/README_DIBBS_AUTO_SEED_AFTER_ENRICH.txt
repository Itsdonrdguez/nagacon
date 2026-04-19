DIBBS auto-seed approved sources after enrich patch

Files included:
- backend/app/services/dibbs/detail_enrichment_playwright.py
- backend/app/api/dibbs_enrich.py

What this changes:
- After successful DIBBS enrichment, the app automatically seeds vendor leads from:
  raw_payload.dibbs_detail.approved_sources
- This happens by default for both:
  - POST /api/dibbs/enrich
  - POST /api/dibbs/enrich-playwright
- You can disable it per request with:
  "auto_seed_approved_sources": false

Expected behavior:
- Enrich opportunity 49
- DIBBS approved source lead for DENTSPLY NORTH AMERICA LLC is auto-created or auto-updated
- Response includes:
  - approved_source_seed on each result
  - approved_source_seed_summary at batch level

Terminal test:
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/dibbs/enrich" -ContentType "application/json" -Body '{"limit":5,"source":"DIBBS","debug":true}' | ConvertTo-Json -Depth 10

Optional single-opportunity test after enrich by checking leads:
Invoke-RestMethod "http://127.0.0.1:8000/api/vendors/leads?opportunity_id=49" | ConvertTo-Json -Depth 10
