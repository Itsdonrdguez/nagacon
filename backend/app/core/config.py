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
            FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")
            CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
            CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX", "")
            SESSION_SECRET = os.getenv("SESSION_SECRET", "")
            SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", "")
            SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax")
            SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
            AUTO_INGEST_ENABLED = os.getenv("AUTO_INGEST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            AUTO_INGEST_POLL_SECONDS = int(os.getenv("AUTO_INGEST_POLL_SECONDS", "900"))
            SEARCH_JOB_RUNNER = os.getenv("SEARCH_JOB_RUNNER", "thread")
            SEARCH_JOB_POLL_SECONDS = float(os.getenv("SEARCH_JOB_POLL_SECONDS", "2.0"))
            SEARCH_JOB_MAX_CONCURRENCY = int(os.getenv("SEARCH_JOB_MAX_CONCURRENCY", "4"))
            DIBBS_FETCH_TIMEOUT_SECONDS = float(os.getenv("DIBBS_FETCH_TIMEOUT_SECONDS", "90"))
            STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
            STORAGE_LOCAL_ROOT = os.getenv("STORAGE_LOCAL_ROOT", "")
            S3_BUCKET = os.getenv("S3_BUCKET", os.getenv("R2_BUCKET", ""))
            S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", os.getenv("R2_ENDPOINT", ""))
            S3_REGION = os.getenv("S3_REGION", "auto")
            S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", os.getenv("R2_ACCESS_KEY_ID", ""))
            S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", os.getenv("R2_SECRET_ACCESS_KEY", ""))
            S3_PUBLIC_BASE_URL = os.getenv("S3_PUBLIC_BASE_URL", "")

        settings = _Settings()
