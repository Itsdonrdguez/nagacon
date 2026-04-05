Add these files preserving paths, then manually add to app/main.py:
from app.api.usaspending_vendor_intel import router as usaspending_vendor_router
app.include_router(usaspending_vendor_router)
