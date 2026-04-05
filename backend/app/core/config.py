from __future__ import annotations

# Compatibility shim for patches that import:
#   from app.core.config import settings
#
# This tries common project layouts first, then falls back to a small env-based
# settings object so imports do not crash startup.

import os

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
            APP_ENV = os.getenv("APP_ENV", "dev")
            DEBUG = os.getenv("DEBUG", "true").lower() in {"1", "true", "yes", "on"}

        settings = _Settings()
