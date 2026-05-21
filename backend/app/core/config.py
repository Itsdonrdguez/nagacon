from __future__ import annotations

# Compatibility shim for patches that import:
#   from app.core.config import settings
#
# This tries common project layouts first, then falls back to a small env-based
# settings object so imports do not crash startup.

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    from app.core.settings import settings  # type: ignore
except Exception:
    try:
        from app.settings import settings  # type: ignore
    except Exception:
        class _Settings:
            DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/nagacon")
            OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
            OPENAI_PROPOSAL_MODEL = os.getenv("OPENAI_PROPOSAL_MODEL", "gpt-4o-mini")
            SAM_API_KEY = os.getenv("SAM_API_KEY")
            SAM_BEARER_TOKEN = os.getenv("SAM_BEARER_TOKEN")
            SMTP_HOST = os.getenv("SMTP_HOST")
            SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
            SMTP_USERNAME = os.getenv("SMTP_USERNAME")
            SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
            SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")
            SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
            EXTERNAL_API_KEYS = os.getenv("EXTERNAL_API_KEYS", "")
            APP_ENV = os.getenv("APP_ENV", "dev")
            APP_ROLE = os.getenv("APP_ROLE", "web")
            DEBUG = os.getenv("DEBUG", "true").lower() in {"1", "true", "yes", "on"}
            DEV_AUTH_FALLBACK_ENABLED = os.getenv("DEV_AUTH_FALLBACK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            SIGNUP_ENABLED = os.getenv("SIGNUP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            DEFAULT_ADMIN_BOOTSTRAP_ENABLED = os.getenv("DEFAULT_ADMIN_BOOTSTRAP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")
            CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
            CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX", "")
            SESSION_SECRET = os.getenv("SESSION_SECRET", "")
            SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", "")
            SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax")
            SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
            AUTO_INGEST_ENABLED = os.getenv("AUTO_INGEST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            AUTO_INGEST_POLL_SECONDS = int(os.getenv("AUTO_INGEST_POLL_SECONDS", "900"))
            DAILY_WORK_ENABLED = os.getenv("DAILY_WORK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            DAILY_WORK_LIMIT = int(os.getenv("DAILY_WORK_LIMIT", "200"))
            DAILY_WORK_RUN_HOUR_LOCAL = int(os.getenv("DAILY_WORK_RUN_HOUR_LOCAL", "6"))
            DAILY_WORK_TIMEZONE = os.getenv("DAILY_WORK_TIMEZONE", "America/New_York")
            AUTO_WORKSPACE_PREP_ENABLED = os.getenv("AUTO_WORKSPACE_PREP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            AUTO_WORKSPACE_PREP_LIMIT = int(os.getenv("AUTO_WORKSPACE_PREP_LIMIT", "0"))
            AUTO_WORKSPACE_PREP_COOLDOWN_HOURS = int(os.getenv("AUTO_WORKSPACE_PREP_COOLDOWN_HOURS", "24"))
            AUTO_CLOSED_WORKSPACE_PREP_ENABLED = os.getenv("AUTO_CLOSED_WORKSPACE_PREP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            AUTO_CLOSED_WORKSPACE_PREP_LIMIT = int(os.getenv("AUTO_CLOSED_WORKSPACE_PREP_LIMIT", "0"))
            AUTO_CLOSED_WORKSPACE_PREP_COOLDOWN_HOURS = int(os.getenv("AUTO_CLOSED_WORKSPACE_PREP_COOLDOWN_HOURS", "24"))
            AUTO_CLOSED_WORKSPACE_STORAGE_CLEANUP_ENABLED = os.getenv("AUTO_CLOSED_WORKSPACE_STORAGE_CLEANUP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            AUTO_FILE_PRUNE_ENABLED = os.getenv("AUTO_FILE_PRUNE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            AUTO_FILE_PRUNE_POLL_SECONDS = int(os.getenv("AUTO_FILE_PRUNE_POLL_SECONDS", "21600"))
            AUTO_FILE_PRUNE_BATCH_SIZE = int(os.getenv("AUTO_FILE_PRUNE_BATCH_SIZE", "100"))
            SEARCH_JOB_RUNNER = os.getenv("SEARCH_JOB_RUNNER", "thread")
            SEARCH_JOB_POLL_SECONDS = float(os.getenv("SEARCH_JOB_POLL_SECONDS", "2.0"))
            SEARCH_JOB_ACTIVE_LIMIT = int(os.getenv("SEARCH_JOB_ACTIVE_LIMIT", "3"))
            SEARCH_JOB_BACKGROUND_ACTIVE_LIMIT = int(os.getenv("SEARCH_JOB_BACKGROUND_ACTIVE_LIMIT", "2"))
            SEARCH_JOB_MAX_CONCURRENCY = int(os.getenv("SEARCH_JOB_MAX_CONCURRENCY", "2"))
            SEARCH_JOB_QUEUE_MAX_CONCURRENCY = int(os.getenv("SEARCH_JOB_QUEUE_MAX_CONCURRENCY", "1"))
            SEARCH_JOB_VENDOR_MAX_CONCURRENCY = int(os.getenv("SEARCH_JOB_VENDOR_MAX_CONCURRENCY", "1"))
            SEARCH_JOB_STALE_SECONDS = int(os.getenv("SEARCH_JOB_STALE_SECONDS", "1800"))
            DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
            DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "2"))
            DB_POOL_TIMEOUT_SECONDS = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))
            DB_POOL_RECYCLE_SECONDS = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))
            WORKSPACE_INTAKE_MAX_PENDING = int(os.getenv("WORKSPACE_INTAKE_MAX_PENDING", "0"))
            WORKSPACE_INTAKE_AUTOMATION_BATCH_LIMIT = int(os.getenv("WORKSPACE_INTAKE_AUTOMATION_BATCH_LIMIT", "0"))
            LOCAL_MODE = os.getenv("LOCAL_MODE", "true").lower() in {"1", "true", "yes", "on"}
            DIBBS_FETCH_TIMEOUT_SECONDS = float(os.getenv("DIBBS_FETCH_TIMEOUT_SECONDS", "90"))
            DIBBS_DEBUG = os.getenv("DIBBS_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
            STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
            STORAGE_LOCAL_ROOT = os.getenv("STORAGE_LOCAL_ROOT", "")
            DOCUMENT_MAX_BYTES = int(os.getenv("DOCUMENT_MAX_BYTES", str(25 * 1024 * 1024)))
            DOCUMENT_PARSER_PAGE_LIMIT = int(os.getenv("DOCUMENT_PARSER_PAGE_LIMIT", "200"))
            DOCUMENT_PARSER_TIMEOUT_SECONDS = float(os.getenv("DOCUMENT_PARSER_TIMEOUT_SECONDS", "30"))
            MALWARE_SCAN_PROVIDER = os.getenv("MALWARE_SCAN_PROVIDER", "")
            PUBLOG_DATA_DIR = os.getenv("PUBLOG_DATA_DIR", "")
            PUBLOG_DVD_ZIP = os.getenv("PUBLOG_DVD_ZIP", "")
            WBPARTS_ENABLED = os.getenv("WBPARTS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            WBPARTS_TIMEOUT_SECONDS = float(os.getenv("WBPARTS_TIMEOUT_SECONDS", "20"))
            WBPARTS_CACHE_DAYS = int(os.getenv("WBPARTS_CACHE_DAYS", "14"))
            S3_BUCKET = os.getenv("S3_BUCKET", os.getenv("R2_BUCKET", ""))
            S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", os.getenv("R2_ENDPOINT", ""))
            S3_REGION = os.getenv("S3_REGION", "auto")
            S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", os.getenv("R2_ACCESS_KEY_ID", ""))
            S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", os.getenv("R2_SECRET_ACCESS_KEY", ""))
            S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL", "")

        settings = _Settings()
