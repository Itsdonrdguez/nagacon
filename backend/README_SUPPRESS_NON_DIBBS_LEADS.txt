SUPPRESS NON-DIBBS LEADS PATCH

Included files:
- backend/app/services/vendors/lead_cleanup.py
- backend/app/api/vendors_lead_cleanup.py
- backend/PATCH_SNIPPET_update_existing_get_leads.txt

What this does:
1. Adds endpoint:
   POST /api/vendors/opportunities/{opportunity_id}/suppress-non-dibbs

2. Suppresses:
   - source_type = USASPENDING_AWARD_HISTORY

3. Only suppresses when at least one:
   - source_type = DIBBS_APPROVED_SOURCE
   exists for that opportunity

4. Suppression behavior:
   - sets status = SUPPRESSED
   - appends a suppression note

Important:
Your existing GET /api/vendors/leads route should be updated to hide suppressed rows by default.
Use the included PATCH_SNIPPET_update_existing_get_leads.txt

main.py wiring:
from app.api.vendors_lead_cleanup import router as vendors_lead_cleanup_router
app.include_router(vendors_lead_cleanup_router)

Recommended flow after DIBBS enrich:
1. DIBBS enrich
2. auto-seed approved sources
3. suppress non-DIBBS leads

Terminal test:
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/vendors/opportunities/49/suppress-non-dibbs" | ConvertTo-Json -Depth 10

Then active-only:
Invoke-RestMethod "http://127.0.0.1:8000/api/vendors/leads?opportunity_id=49" | ConvertTo-Json -Depth 10

Then full list:
Invoke-RestMethod "http://127.0.0.1:8000/api/vendors/leads?opportunity_id=49&include_suppressed=true" | ConvertTo-Json -Depth 10
