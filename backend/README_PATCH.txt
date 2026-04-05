COMPLETE PATCH

Replace these files in your project:
- app/services/dibbs/session.py
- app/services/dibbs_adapter.py

This fixes the current startup blocker:
- session.py had literal \n characters causing a SyntaxError
- session.py now includes page_html(), which other DIBBS services import
- dibbs_adapter.py is a complete valid module, not placeholder text

After replacing the files:
1. Restart:
   uvicorn app.main:app --reload

2. Test:
   Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/scrapers/dibbs/run" `
   -ContentType "application/json" `
   -Body '{"max_pages":1,"fsc":"6520","limit":10,"debug":true}' |
   ConvertTo-Json -Depth 10
