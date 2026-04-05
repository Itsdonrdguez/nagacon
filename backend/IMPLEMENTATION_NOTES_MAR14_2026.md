# NagaCon patch set — March 14, 2026

This package starts from the uploaded backend and Streamlit zips and adds the latest implementation work discussed in chat.

## What was added

### 1. Opportunity ingestion foundation
New modules:
- `app/schemas/opportunity.py`
- `app/repositories/opportunities.py`
- `app/services/opportunities/normalize.py`
- `app/services/opportunities/deduplicate.py`
- `app/services/opportunities/ingest.py`
- `app/api/opportunities.py`

What it does:
- defines a `RawOpportunity` input contract for scraper output
- normalizes raw opportunity records defensively
- supports exact dedupe by:
  - `source + source_opportunity_id`
  - fallback `source + solicitation_number`
- supports fuzzy duplicate detection using `rapidfuzz`
- returns structured ingestion results:
  - `inserted`
  - `updated`
  - `skipped`
  - `errors`

### 2. Scraper API endpoints
New routes:
- `POST /api/scrapers/sam/run`
- `POST /api/scrapers/dibbs/run`

New modules:
- `app/services/scrapers/sam_scraper.py`
- `app/services/scrapers/dibbs_scraper.py`

Notes:
- SAM is wired as a real ingestion entry point and expects `SAM_API_KEY` in the environment.
- DIBBS route wraps the existing DIBBS adapter and converts its output into the new raw-ingestion format.

### 3. Opportunity model/file model extensions
Updated models:
- `app/models/opportunity.py`
- `app/models/opportunity_file.py`

Added fields:
- opportunities:
  - `source_opportunity_id`
  - `sub_agency`
  - `office`
  - `place_of_performance`
  - `raw_payload`
- opportunity_files:
  - `extracted_text`
  - `parsed_metadata`

### 4. Document parsing
New module:
- `app/services/document_parser.py`

Updated route:
- `POST /api/files/parse/{file_id}`

What it does:
- parses saved PDFs using PyMuPDF
- counts tables with `pdfplumber`
- stores extracted text and metadata on `opportunity_files`

### 5. Main app wiring and backend error handling
Updated:
- `app/main.py`

Added:
- new routers for opportunities and scrapers
- simple global and HTTP exception handlers

### 6. Streamlit helpers
New frontend helpers:
- `streamlit_app/api_opportunities.py`
- `streamlit_app/api_documents.py`

These make it easier to call the new backend endpoints from the UI.

### 7. Alembic migration
Added migration:
- `alembic/versions/f1a2b3c4d5e6_step9_ingestion_foundation.py`

### 8. Dependency updates
Updated:
- `pyproject.toml`

Added dependencies:
- `requests`
- `rapidfuzz`
- `pymupdf`
- `pdfplumber`

## What I intentionally did not overreach on

I did **not** try to rewrite the whole backend into a new architecture, because the uploaded project already had working DIBBS/workspace/vendor flows.

So this patch set is **additive**:
- it preserves the existing routes and services
- it adds the new ingestion foundation alongside the existing app
- it avoids destructive refactors that could break the current workspace flow

## What still remains a next-step item

These are not fully finished in this patch set:
- validating the SAM response mapping against live API output in your environment
- a fully hardened DIBBS scraper beyond the current adapter-wrapper approach
- wiring the new Streamlit helpers into the pages more deeply
- full workspace aggregation based on the new opportunity ingestion foundation
- a deeper vendor discovery engine beyond the current vendor lead / quote workflow already in the project

## Suggested local test order

1. Install/update backend deps
2. Run Alembic migration
3. Start FastAPI
4. Test:
   - `POST /api/opportunities/ingest`
   - `POST /api/scrapers/dibbs/run`
   - `POST /api/files/parse/{file_id}`
5. Start Streamlit and use the existing UI plus the new helpers as needed
