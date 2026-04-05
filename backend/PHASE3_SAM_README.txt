PHASE 3 PATCH - SAM API VERIFY

What was added:
- Fixed SAM_API_KEY environment variable loading in app/core/config.py
- Added POST /api/scrapers/sam/verify for a no-ingest SAM connectivity check
- Updated POST /api/scrapers/sam/run to optionally return debug diagnostics
- Updated Streamlit Opportunities page with "Verify SAM API"
- Updated System Status page with SAM verification and ingest diagnostics
- Updated backend_smoke_test.py to write backend_system_checks.json including SAM verification

How to use:
1) Add this to your backend .env:
   SAM_API_KEY=your_real_sam_key_here
   SAM_BEARER_TOKEN=optional_only_if_you_use_one

2) Start backend
   uvicorn app.main:app --reload

3) Verify only (no ingest)
   POST http://127.0.0.1:8000/api/scrapers/sam/verify
   body example:
   {
     "limit": 5,
     "q": "medical"
   }

4) Ingest from SAM with diagnostics
   POST http://127.0.0.1:8000/api/scrapers/sam/run
   body example:
   {
     "limit": 5,
     "q": "medical",
     "debug": true
   }

5) In Streamlit
   - Opportunities page -> Ingest SAM popover -> Verify SAM API
   - System Status page -> Verify SAM API / Run SAM route
