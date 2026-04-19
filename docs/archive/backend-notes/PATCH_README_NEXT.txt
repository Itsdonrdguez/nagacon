This patch fixes the backend startup crash and wiring gaps:
- adds PipelineStatus enum
- includes analytics/pipeline/quotes/company/agents routers in app/main.py
- allows workspace endpoints to accept opp_id or opportunity_id
- allows files/download_pdfs to accept JSON body or query param
- fixes files/parse/{file_id} to parse from file path
- allows phase3 suggested-quote without vendor_lead_id by falling back to first lead
- makes USAspending research endpoints fail gracefully on connection errors
