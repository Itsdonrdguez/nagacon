NagaCon Phase 4

What changed
- SAM opportunities now normalize into the main opportunities flow more cleanly.
- Added duplicate handling by source id, solicitation number, URL, and title similarity.
- Added /api/scrapers/sam/verify to test SAM before ingest.
- Opportunities API now supports filters for search, source, decision status, NAICS, and set-aside.
- Opportunities list now returns workspace_url and decision_status.
- Added /api/opportunities/{id}/workspace.
- Enabled pipeline router in FastAPI app.
- Fixed Workspace pipeline save bug so it updates the pipeline item instead of using the opportunity id.
- Simplified Opportunities page and added a clearer Bid / Not Bid column.

Recommended checks
1. Start backend.
2. Verify SAM from UI or POST /api/scrapers/sam/verify.
3. Run SAM ingest with debug=true.
4. Open an opportunity from Opportunities into Workspace.
5. Initialize Pipeline and save BID / NO_BID.
6. Return to Opportunities and confirm Bid / Not Bid status shows there.
