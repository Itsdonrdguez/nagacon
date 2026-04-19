DIBBS approved-source-to-vendor-leads seeding patch

Files included:
- backend/app/api/vendors_dibbs_approved_sources.py
- backend/app/services/dibbs/approved_source_leads.py

What it does:
- reads raw_payload.dibbs_detail.approved_sources
- creates VendorLead rows directly from DIBBS approved sources
- marks them as:
  - source_type = DIBBS_APPROVED_SOURCE
  - is_approved_source = True
- carries over:
  - cage
  - part_number
  - company_name
  - nsn
- de-duplicates by CAGE first, then company + part number

New endpoint:
POST /api/vendors/dibbs/approved-sources/seed
Body:
{
  "opportunity_id": 49
}

Important wiring in app/main.py:
from app.api.vendors_dibbs_approved_sources import router as vendors_dibbs_approved_sources_router
app.include_router(vendors_dibbs_approved_sources_router)

Terminal test:
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/vendors/dibbs/approved-sources/seed" -ContentType "application/json" -Body '{"opportunity_id":49}' | ConvertTo-Json -Depth 10

Then verify:
Invoke-RestMethod "http://127.0.0.1:8000/api/vendors/leads?opportunity_id=49" | ConvertTo-Json -Depth 10
