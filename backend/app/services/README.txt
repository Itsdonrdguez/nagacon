Replace these files:
- backend/app/services/dibbs_adapter.py
- backend/app/services/dibbs_scraper.py

This fix specifically resolves:
pull_dibbs_by_fsc() got an unexpected keyword argument 'fsc_raw'

Why:
Your route is calling pull_dibbs_by_fsc(fsc_raw=...), while the prior patched adapter only accepted fsc=...
This version accepts BOTH:
- fsc=
- fsc_raw=

Then restart:
uvicorn app.main:app --reload

Then test:
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/scrapers/dibbs/run" `
-ContentType "application/json" `
-Body '{"max_pages":1,"fsc":"6520","limit":10,"debug":true}' |
ConvertTo-Json -Depth 10
