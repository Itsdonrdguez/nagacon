PATCH CONTENTS
- Fixed Opportunity model alias compatibility so naics_code/fsc_code/set_aside_type/description are accepted.
- Fixed dibbs_adapter signature so both fsc_raw= and fsc= work.
- Removed naics_code from adapter output to avoid stale-path insert crashes.
- Filtered junk DIBBS pages at adapter + scraper levels:
  - removes RfqDates.aspx
  - removes Default.aspx
  - removes archive zip/txt pages
  - keeps RFQNsn.aspx / RFQ solicitation detail pages only
- Updated Streamlit opportunities page to use workspace_url when present.

TEST COMMANDS

1) Restart backend
uvicorn app.main:app --reload

2) Test DIBBS scrape
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/scrapers/dibbs/run" `
-ContentType "application/json" `
-Body '{"max_pages":1,"fsc":"6520","limit":10,"debug":true}' |
ConvertTo-Json -Depth 10

Expected:
- no "unexpected keyword argument fsc_raw"
- no "naics_code is an invalid keyword argument for Opportunity"
- rows_parsed > 0

3) Test enrichment pipeline
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/dibbs/pipeline" `
-ContentType "application/json" `
-Body '{"limit":10,"debug":true}' |
ConvertTo-Json -Depth 20

Expected:
- DIBBS RFQ NSN Page entries only for new ingested items
- fewer/no RfqDates.aspx or Default.aspx opportunities going forward

4) Optional cleanup idea:
Existing junk opportunities already in DB will still enrich until removed.
If you want, upload backend again after testing and I’ll patch a one-click cleanup endpoint.
