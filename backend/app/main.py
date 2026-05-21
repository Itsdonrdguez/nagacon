from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from app.core.config import settings
from app.services.auth_service import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

from app.api.dibbs import router as dibbs_router
from app.api.bid_submissions import router as submissions_router
from app.api.data_health import router as data_health_router
from app.api.dibbs_enrich import router as dibbs_enrich_router
from app.api.export import router as export_router
from app.api.notifications import router as notifications_router
from app.api.opportunities import router as opportunities_router
from app.api.parts import router as parts_router
from app.api.proposal_assist import router as proposal_assist_router
from app.api.phase3 import router as phase3_router
from app.api.research import router as research_router
from app.api.scoring import router as scoring_router
from app.api.scrapers import router as scrapers_router
from app.api.search_jobs import router as search_jobs_router
from app.api.saas_readiness import router as saas_readiness_router
from app.api.source_freshness import router as source_freshness_router
from app.api.usaspending_vendor_intel import router as usaspending_vendor_intel_router
from app.api.vendor_discovery import router as vendor_discovery_router
from app.api.vendor_email import router as vendor_email_router
from app.api.vendors import router as vendors_router
from app.api.vendors_dibbs_approved_sources import router as vendors_dibbs_approved_sources_router
from app.api.vendors_lead_cleanup import router as vendors_lead_cleanup_router
from app.api.work_queue import router as work_queue_router
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
from app.services.auto_file_prune_scheduler import start_auto_file_prune_worker, stop_auto_file_prune_worker
from app.services.search_job_recovery_scheduler import start_search_job_recovery_worker, stop_search_job_recovery_worker

load_dotenv()

LOCAL_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]

PROTECTED_APP_ENVS = {"prod", "production", "private-alpha", "private_alpha"}
UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER_NAME = "X-CSRF-Token"


def _is_protected_env() -> bool:
    return str(getattr(settings, "APP_ENV", "dev") or "dev").strip().lower() in PROTECTED_APP_ENVS


def validate_startup_config() -> None:
    if not _is_protected_env():
        return

    errors: list[str] = []
    session_secret = str(getattr(settings, "SESSION_SECRET", "") or "").strip()
    if bool(getattr(settings, "DEBUG", False)):
        errors.append("DEBUG must be false")
    if bool(getattr(settings, "DEV_AUTH_FALLBACK_ENABLED", True)):
        errors.append("DEV_AUTH_FALLBACK_ENABLED must be false")
    if bool(getattr(settings, "SIGNUP_ENABLED", True)):
        errors.append("SIGNUP_ENABLED must be false")
    if not bool(getattr(settings, "SESSION_COOKIE_SECURE", False)):
        errors.append("SESSION_COOKIE_SECURE must be true")
    if not session_secret or session_secret.lower() in {
        "replace-with-a-long-random-secret",
        "changeme",
        "secret",
        "dev-secret",
    } or len(session_secret) < 24:
        errors.append("SESSION_SECRET must be a non-default secret with at least 24 characters")
    if bool(getattr(settings, "DEFAULT_ADMIN_BOOTSTRAP_ENABLED", True)):
        errors.append("default development password bootstrap must be disabled before protected deployment")

    if errors:
        raise RuntimeError("Unsafe protected deployment configuration: " + "; ".join(errors))


def _cors_origins() -> list[str]:
    configured: list[str] = []
    for raw in [getattr(settings, "FRONTEND_ORIGIN", ""), getattr(settings, "CORS_ORIGINS", "")]:
        for item in str(raw or "").split(","):
            value = item.strip()
            if value and value not in configured:
                configured.append(value)
    app_env = str(getattr(settings, "APP_ENV", "dev")).lower()
    if app_env in {"prod", "production"}:
        return configured or LOCAL_CORS_ORIGINS
    return LOCAL_CORS_ORIGINS + [item for item in configured if item not in LOCAL_CORS_ORIGINS]


def _cors_origin_regex() -> str | None:
    configured_regex = str(getattr(settings, "CORS_ORIGIN_REGEX", "") or "").strip()
    if configured_regex:
        return configured_regex
    configured_origins = _cors_origins()
    if any("vercel.app" in origin for origin in configured_origins):
        return r"^https://.*\.vercel\.app$"
    return None

CORE_ROUTERS = [
    health_router,
    auth_router,
    opportunities_router,
    parts_router,
    notifications_router,
    source_freshness_router,
    data_health_router,
    saas_readiness_router,
    workspace_router,
    pipeline_router,
    providers_router,
    nsn_router,
    company_router,
    organizations_router,
    files_router,
    scrapers_router,
    search_jobs_router,
    work_queue_router,
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
    start_search_job_recovery_worker(app)
    start_auto_ingest_worker(app)
    start_auto_file_prune_worker(app)
    try:
        yield
    finally:
        stop_auto_file_prune_worker(app)
        stop_auto_ingest_worker(app)
        stop_search_job_recovery_worker(app)


def create_app() -> FastAPI:
    validate_startup_config()
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
        allow_origins=_cors_origins(),
        allow_origin_regex=_cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        if request.method.upper() in UNSAFE_HTTP_METHODS:
            path = request.url.path or ""
            if not path.startswith("/api/integrations") and not path.startswith("/api/auth/"):
                session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
                session_header = request.headers.get("X-Session-Token")
                if session_cookie and not session_header:
                    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
                    csrf_header = request.headers.get(CSRF_HEADER_NAME)
                    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "CSRF token missing or invalid"},
                        )
        return await call_next(request)

    for router in CORE_ROUTERS + RESEARCH_AND_VENDOR_ROUTERS + SUPPORT_ROUTERS + LEGACY_COMPAT_ROUTERS:
        app.include_router(router)
    app.include_router(integrations_router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        content = {"detail": "Internal server error"}
        if bool(getattr(settings, "DEBUG", False)):
            content["error"] = str(exc)
        return JSONResponse(status_code=500, content=content)

    return app

app = create_app()
