from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from app.core.config import settings
from app.schemas.opportunity import RawOpportunity
from app.services.scrapers.dibbs_scraper import fetch_dibbs_opportunities


def dibbs_fetch_timeout_seconds() -> float:
    try:
        return max(5.0, float(getattr(settings, "DIBBS_FETCH_TIMEOUT_SECONDS", 90) or 90))
    except Exception:
        return 90.0


def guarded_fetch_dibbs_opportunities(
    params: dict[str, Any],
    *,
    max_pages: int,
    timeout_seconds: float | None = None,
) -> list[RawOpportunity]:
    wait_seconds = timeout_seconds if timeout_seconds is not None else dibbs_fetch_timeout_seconds()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dibbs-fetch") as executor:
        future = executor.submit(fetch_dibbs_opportunities, params=params, max_pages=max_pages)
        try:
            return future.result(timeout=wait_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            fsc = str((params or {}).get("fsc") or (params or {}).get("fsc_code") or "").strip() or "unknown"
            raise TimeoutError(
                f"DIBBS fetch timed out after {int(wait_seconds)}s for FSC {fsc}"
            ) from exc
