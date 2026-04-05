from dotenv import load_dotenv
import os

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.dibbs import router as dibbs_router
from app.api.scoring import router as scoring_router
from app.api.dibbs_enrich import router as dibbs_enrich_router
from app.api.workspace import router as workspace_router
from app.api.vendors import router as vendors_router
from app.api.export import router as export_router
from app.api.bid_submissions import router as submissions_router
from app.api.files import router as files_router
from app.api.opportunities import router as opportunities_router
from app.api.scrapers import router as scrapers_router
from app.api.vendor_discovery import router as vendor_discovery_router
from app.api.proposal_assist import router as proposal_assist_router
from app.api.vendor_email import router as vendor_email_router
from app.api.research import router as research_router
from app.api.usaspending_vendor_intel import router as usaspending_vendor_intel_router
from app.api.routes.health_check import router as health_router
from app.api.routes.research_predecessor import router as research_predecessor_router
from app.api.dibbs_enrich_playwright import router as dibbs_enrich_pw_router
from app.api.vendors_dibbs_approved_sources import router as vendors_dibbs_approved_sources_router
from app.api.vendors_lead_cleanup import router as vendors_lead_cleanup_router
from app.api.phase3 import router as phase3_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.pipeline import router as pipeline_router
from app.api.routes.quotes import router as quotes_router
from app.api.routes.company import router as company_router
from app.api.routes.agents import router as agents_router

app = FastAPI(title="NagaCon")

# CORS FIX
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core routers
app.include_router(dibbs_router)
app.include_router(scoring_router)
app.include_router(dibbs_enrich_router)
app.include_router(workspace_router)
app.include_router(vendors_router)
app.include_router(export_router)
app.include_router(submissions_router)
app.include_router(files_router)
app.include_router(opportunities_router)
app.include_router(scrapers_router)
app.include_router(vendor_discovery_router)
app.include_router(proposal_assist_router)
app.include_router(vendor_email_router)
app.include_router(research_router)
app.include_router(usaspending_vendor_intel_router)
app.include_router(health_router)
app.include_router(research_predecessor_router)
app.include_router(vendors_dibbs_approved_sources_router)

# Playwright DIBBS enrichment
app.include_router(dibbs_enrich_pw_router)
app.include_router(vendors_lead_cleanup_router)
app.include_router(phase3_router)

app.include_router(analytics_router)
app.include_router(pipeline_router)
app.include_router(quotes_router)
app.include_router(company_router)
app.include_router(agents_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )
