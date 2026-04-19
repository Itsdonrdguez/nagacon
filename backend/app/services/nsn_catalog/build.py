from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.nsn_catalog.catalog_service import get_nsn_catalog_summary
from app.services.nsn_catalog.normalizer import normalize_nsn
from app.services.nsn_catalog.publog_decomp import import_publog_nsn
from app.services.nsn_catalog.refresh import refresh_nsn_intelligence


def build_nsn_intelligence(
    db: Session,
    nsn: str,
    *,
    seed_providers: bool = True,
    run_usaspending: bool = True,
    limit: int = 50,
    organization_id: int | None = None,
) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {"status": "invalid_nsn", "error": "NSN must contain exactly 13 digits."}

    publog_result = import_publog_nsn(db, target.nsn)
    if publog_result.get("status") not in {"ok"}:
        return {
            "status": "publog_failed",
            "nsn": target.nsn,
            "publog": publog_result,
            "summary": get_nsn_catalog_summary(db, target.nsn),
        }

    refresh_result = refresh_nsn_intelligence(
        db,
        target.nsn,
        run_usaspending=run_usaspending,
        seed_providers=seed_providers,
        limit=limit,
        organization_id=organization_id,
    )
    return {
        "status": "ok" if refresh_result.get("status") == "ok" else refresh_result.get("status"),
        "nsn": target.nsn,
        "publog": publog_result,
        "refresh": refresh_result,
        "summary": get_nsn_catalog_summary(db, target.nsn),
    }
