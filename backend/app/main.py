from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from app.api.dibbs import router as dibbs_router
from app.api.bid_submissions import router as submissions_router
from app.api.dibbs_enrich import router as dibbs_enrich_router
from app.api.export import router as export_router
from app.api.opportunities import router as opportunities_router
from app.api.proposal_assist import router as proposal_assist_router
from app.api.phase3 import router as phase3_router
from app.api.research import router as research_router
from app.api.scoring import router as scoring_router
from app.api.scrapers import router as scrapers_router
from app.api.search_jobs import router as search_jobs_router
from app.api.usaspending_vendor_intel import router as usaspending_vendor_intel_router
from app.api.vendor_discovery import router as vendor_discovery_router
from app.api.vendor_email import router as vendor_email_router
from app.api.vendors import router as vendors_router
from app.api.vendors_dibbs_approved_sources import router as vendors_dibbs_approved_sources_router
from app.api.vendors_lead_cleanup import router as vendors_lead_cleanup_router
from app.api.workspace import router as workspace_router
from app.api.routes.agents import router as agents_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.auth import router as auth_router
from app.api.routes.company import router as company_router
from app.api.routes.health_check import router as health_router
from app.api.routes.nsn import router as nsn_router
from app.api.routes.organizations import router as organizations_router
from app.api.routes.pipeline import router as pipeline_router
from app.api.routes.providers import router as providers_router
from app.api.routes.quotes import router as quotes_router
from app.api.routes.research_predecessor import router as research_predecessor_router
from app.api.routes.settings import router as settings_router
from app.api.files import router as files_router
from app.api.integrations import router as integrations_router
from app.services.auto_ingest_scheduler import start_auto_ingest_worker, stop_auto_ingest_worker

load_dotenv()

LOCAL_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]

CORE_ROUTERS = [
    health_router,
    auth_router,
    opportunities_router,
    workspace_router,
    pipeline_router,
    providers_router,
    nsn_router,
    company_router,
    organizations_router,
    files_router,
    scrapers_router,
    search_jobs_router,
    submissions_router,
    settings_router,
]

RESEARCH_AND_VENDOR_ROUTERS = [
    dibbs_router,
    dibbs_enrich_router,
    vendors_router,
    vendors_dibbs_approved_sources_router,
    vendors_lead_cleanup_router,
    vendor_discovery_router,
    usaspending_vendor_intel_router,
    research_router,
    research_predecessor_router,
]

SUPPORT_ROUTERS = [
    scoring_router,
    quotes_router,
    analytics_router,
    proposal_assist_router,
    vendor_email_router,
    export_router,
]

LEGACY_COMPAT_ROUTERS = [
    phase3_router,
    agents_router,
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_auto_ingest_worker(app)
    try:
        yield
    finally:
        stop_auto_ingest_worker(app)


def create_app() -> FastAPI:
    app = FastAPI(
        title="NagaCon",
        description=(
            "NagaCon GovCon intelligence platform API. "
            "Internal UI routes remain under /api/*, and external clients should use the "
            "API-key-protected integration surface under /api/integrations with the X-API-Key header."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in CORE_ROUTERS + RESEARCH_AND_VENDOR_ROUTERS + SUPPORT_ROUTERS + LEGACY_COMPAT_ROUTERS:
        app.include_router(router)
    app.include_router(integrations_router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": str(exc)},
        )

    return app

app = create_app()
