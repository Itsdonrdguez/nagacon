from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.db import get_db
from app.schemas.opportunity import RawOpportunity
from app.services.dibbs.fetch_guard import guarded_fetch_dibbs_opportunities
from app.services.ingest_enrichment import enrich_dibbs_opportunities_after_ingest
from app.services.opportunity_ingest import find_existing_opportunity
from app.services.opportunity_ingest import upsert_raw_opportunity
from app.services.provider_settings_service import get_effective_sam_api_key
from app.services.scrapers.dibbs_scraper import fetch_dibbs_opportunities
from app.services.scrapers.sam_scraper import SamScraperError, fetch_sam_opportunities
from app.services.scrapers.state_local_scraper import (
    fetch_dc_opportunities,
    fetch_eva_opportunities,
    fetch_maryland_opportunities,
)

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"])


def _parse_code_list(value: str | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    codes: list[str] = []
    for part in str(value).split(","):
        code = part.strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def _normalize_dibbs_fsc(value: str) -> str | None:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) >= 4:
        return digits[:4]
    return None


def _extract_dibbs_fsc_list(value: str | None) -> list[str]:
    seen: set[str] = set()
    fsc_codes: list[str] = []
    for token in _parse_code_list(value):
        fsc = _normalize_dibbs_fsc(token)
        if not fsc or fsc in seen:
            continue
        seen.add(fsc)
        fsc_codes.append(fsc)
    return fsc_codes


def _sam_code_payload(
    code: str,
    limit: int,
    posted_from: str | None,
    posted_to: str | None,
    sam_filters: dict[str, Any] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "limit": limit,
        "postedFrom": posted_from,
        "postedTo": posted_to,
    }
    sam_filters = sam_filters or {}
    if sam_filters.get("state"):
        payload["state"] = sam_filters["state"]
    if sam_filters.get("zip"):
        payload["zip"] = sam_filters["zip"]
    if sam_filters.get("organizationName"):
        payload["organizationName"] = sam_filters["organizationName"]
    if sam_filters.get("organizationCode"):
        payload["organizationCode"] = sam_filters["organizationCode"]
    if api_key:
        payload["api_key"] = api_key
    cleaned = str(code or "").strip()
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if len(digits) == 6:
        payload["ncode"] = digits
    else:
        payload["ccode"] = cleaned
    return payload


def _sam_search_type(code: str) -> str:
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    return "naics" if len(digits) == 6 else "psc"


def _fetch_sam_code_opportunities(
    code: str,
    *,
    limit: int,
    posted_from: str | None,
    posted_to: str | None,
    sam_filters: dict[str, Any] | None = None,
    api_key: str | None = None,
    all_results: bool = False,
    page_size: int = 100,
    safety_limit: int = 5000,
) -> list[RawOpportunity]:
    if not all_results:
        return fetch_sam_opportunities(_sam_code_payload(code, limit, posted_from, posted_to, sam_filters, api_key))

    collected: list[RawOpportunity] = []
    seen: set[tuple[str | None, str | None]] = set()
    offset = 0
    page_limit = max(1, page_size)
    while len(collected) < safety_limit:
        payload = _sam_code_payload(code, page_limit, posted_from, posted_to, sam_filters, api_key)
        payload["offset"] = offset
        rows = fetch_sam_opportunities(payload)
        if not rows:
            break
        for row in rows:
            key = (row.source_opportunity_id, row.solicitation_number)
            if key in seen:
                continue
            seen.add(key)
            collected.append(row)
            if len(collected) >= safety_limit:
                break
        if len(rows) < page_limit:
            break
        offset += page_limit
    return collected


def _dedupe_raw_opportunities(raw_opps: list[RawOpportunity]) -> list[RawOpportunity]:
    seen: set[tuple[str | None, str | None, str | None, str | None]] = set()
    unique: list[RawOpportunity] = []
    for raw in raw_opps:
        key = (
            raw.source,
            raw.source_opportunity_id,
            raw.solicitation_number,
            raw.url,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)
    return unique


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _ingest_many(
    db: Session,
    raw_opps: list[RawOpportunity],
    *,
    auto_enrich_dibbs: bool = False,
    queue_nsn_build: bool = False,
    organization_id: int | None = None,
) -> dict[str, Any]:
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    dibbs_opportunity_ids: list[int] = []

    for raw in raw_opps:
        try:
            result = upsert_raw_opportunity(db, raw, force_refresh=True, organization_id=organization_id)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
            if str(raw.source or "").upper() == "DIBBS":
                opp = find_existing_opportunity(db, raw)
                if opp and getattr(opp, "id", None):
                    dibbs_opportunity_ids.append(opp.id)
        except Exception as exc:
            db.rollback()
            errors.append(str(exc))

    out = {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
    if auto_enrich_dibbs and dibbs_opportunity_ids:
        out["part_finder_enrichment"] = enrich_dibbs_opportunities_after_ingest(
            db,
            dibbs_opportunity_ids,
            organization_id=organization_id,
            queue_nsn_build=queue_nsn_build,
            max_items=len(dibbs_opportunity_ids),
        )
    return out


@router.post("/sam/run")
def run_sam_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        payload = dict(payload or {})
        api_key = get_effective_sam_api_key(db, user_id=getattr(current_user, "id", None))
        if api_key:
            payload["api_key"] = api_key
        raw_opps = fetch_sam_opportunities(payload)
        out = _ingest_many(db, raw_opps)
        if (payload or {}).get("debug"):
            out["diagnostics"] = {
                "request": payload or {},
                "rows_parsed": len(raw_opps),
                "source": "sam.gov",
            }
        return out
    except SamScraperError as exc:
        return {
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [str(exc)],
            "diagnostics": {"request": payload or {}, "rows_parsed": 0, "source": "sam.gov"},
        }


@router.post("/dibbs/run")
def run_dibbs_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.get("max_pages") or 4)
    raw_opps = fetch_dibbs_opportunities(params=payload, max_pages=max_pages)
    out = _ingest_many(
        db,
        raw_opps,
        auto_enrich_dibbs=_as_bool(payload.get("auto_enrich_parts"), True),
        queue_nsn_build=_as_bool(payload.get("queue_nsn_build"), False),
    )
    if payload.get("debug"):
        out["diagnostics"] = {
            "request_fsc": payload.get("fsc") or payload.get("fsc_code"),
            "request_limit": int(payload.get("limit") or payload.get("page_size") or 25),
            "pages_fetched": max_pages,
            "rows_parsed": len(raw_opps),
            "mode": "adapter",
        }
    return out


@router.post("/state-local/eva/run")
def run_eva_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.pop("max_pages", 2))
    return _ingest_many(db, fetch_eva_opportunities(params=payload, max_pages=max_pages))


@router.post("/state-local/maryland/run")
def run_maryland_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.pop("max_pages", 2))
    return _ingest_many(db, fetch_maryland_opportunities(params=payload, max_pages=max_pages))


@router.post("/state-local/dc/run")
def run_dc_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})
    max_pages = int(payload.pop("max_pages", 2))
    return _ingest_many(db, fetch_dc_opportunities(params=payload, max_pages=max_pages))


@router.post("/state-local/all/run")
def run_all_state_local(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
):
    payload = dict(payload or {})

    eva_params = dict(payload)
    md_params = dict(payload)
    dc_params = dict(payload)

    result = {}
    try:
        result["eva"] = _ingest_many(db, fetch_eva_opportunities(params=eva_params, max_pages=int(eva_params.pop("max_pages", 2))))
    except Exception as exc:
        result["eva"] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}
    try:
        result["maryland"] = _ingest_many(db, fetch_maryland_opportunities(params=md_params, max_pages=int(md_params.pop("max_pages", 2))))
    except Exception as exc:
        result["maryland"] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}
    try:
        result["dc"] = _ingest_many(db, fetch_dc_opportunities(params=dc_params, max_pages=int(dc_params.pop("max_pages", 2))))
    except Exception as exc:
        result["dc"] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": [str(exc)]}

    return result


def run_multi_source_search(
    payload: dict,
    db: Session,
    *,
    user_id: int | None = None,
    progress_callback=None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    query_text = (payload.get("q") or payload.get("query") or "").strip()
    limit = int(payload.get("per_code_limit") or payload.get("per_target_limit") or payload.get("limit") or 25)
    limit_mode = str(payload.get("limit_mode") or "per_code").strip().lower()
    total_result_limit = int(payload.get("total_result_limit") or payload.get("result_limit") or limit)
    use_total_result_limit = limit_mode in {"total", "records", "results"}
    use_all_results = limit_mode in {"all", "all_records", "deep_all"}
    posted_from = payload.get("postedFrom")
    posted_to = payload.get("postedTo")
    sam_filters = {
        "state": (payload.get("sam_state") or payload.get("state") or "").strip().upper() or None,
        "zip": (payload.get("sam_zip") or payload.get("zip") or "").strip() or None,
        "organizationName": (payload.get("sam_agency") or payload.get("organizationName") or "").strip() or None,
        "organizationCode": (payload.get("sam_agency_code") or payload.get("organizationCode") or "").strip() or None,
    }
    sam_api_key = get_effective_sam_api_key(db, user_id=user_id)

    sources = payload.get("sources") or ["SAM", "DIBBS"]
    sources = [str(source).upper() for source in sources]

    results: dict[str, Any] = {}
    notices: list[str] = []
    totals = {"inserted": 0, "updated": 0, "skipped": 0, "errors": []}
    query_diagnostics: dict[str, Any] = {}
    sam_codes = _parse_code_list(query_text) if "SAM" in sources else []
    dibbs_fsc_codes = _extract_dibbs_fsc_list(payload.get("fsc") or query_text) if "DIBBS" in sources else []
    total_steps = len(sam_codes) + len(dibbs_fsc_codes)
    completed_steps = 0
    total_budget_remaining = max(total_result_limit, 0)

    def _progress(source: str, label: str, raw_rows: int | None = None) -> None:
        if not progress_callback:
            return
        progress_callback(
            {
                "source": source,
                "label": label,
                "raw_rows": raw_rows,
                "completed_steps": completed_steps,
                "total_steps": total_steps,
            }
        )

    _progress("Search", "Preparing sources", None)

    if "SAM" in sources:
        sam_code_results: list[dict[str, Any]] = []
        try:
            sam_raw: list[RawOpportunity] = []
            for sam_code in sam_codes:
                if use_total_result_limit and total_budget_remaining <= 0:
                    sam_code_results.append(
                        {
                            "code": sam_code,
                            "search_type": _sam_search_type(sam_code),
                            "raw_rows": 0,
                            "skipped_reason": "total result limit reached",
                        }
                    )
                    completed_steps += 1
                    _progress("SAM", sam_code, 0)
                    continue
                code_limit = min(limit, total_budget_remaining) if use_total_result_limit else limit
                sam_code_raw = _fetch_sam_code_opportunities(
                    sam_code,
                    limit=code_limit,
                    posted_from=posted_from,
                    posted_to=posted_to,
                    sam_filters=sam_filters,
                    api_key=sam_api_key,
                    all_results=use_all_results,
                    page_size=int(payload.get("sam_page_size") or 100),
                    safety_limit=int(payload.get("sam_safety_limit") or 5000),
                )
                if use_total_result_limit:
                    sam_code_raw = sam_code_raw[:total_budget_remaining]
                    total_budget_remaining -= len(sam_code_raw)
                completed_steps += 1
                _progress("SAM", sam_code, len(sam_code_raw))
                sam_code_results.append(
                    {
                        "code": sam_code,
                        "search_type": _sam_search_type(sam_code),
                        "raw_rows": len(sam_code_raw),
                    }
                )
                sam_raw.extend(sam_code_raw)
            sam_raw = _dedupe_raw_opportunities(sam_raw)
            sam_result = _ingest_many(db, sam_raw)
            sam_result["diagnostics"] = {
                "used_codes": sam_codes,
                "per_code_limit": limit,
                "limit_mode": limit_mode,
                "total_result_limit": total_result_limit if use_total_result_limit else None,
                "all_results": use_all_results,
                "sam_filters": {key: value for key, value in sam_filters.items() if value},
                "raw_rows": len(sam_raw),
                "code_results": sam_code_results,
            }
        except SamScraperError as exc:
            sam_result = {
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [str(exc)],
                "diagnostics": {
                    "used_codes": sam_codes,
                    "per_code_limit": limit,
                    "limit_mode": limit_mode,
                    "total_result_limit": total_result_limit if use_total_result_limit else None,
                    "all_results": use_all_results,
                    "sam_filters": {key: value for key, value in sam_filters.items() if value},
                    "raw_rows": 0,
                    "code_results": sam_code_results,
                },
            }
        if not sam_codes:
            notices.append("SAM search expects NAICS, PSC, or classification codes. You can enter multiple codes separated by commas.")
        results["sam"] = sam_result
        query_diagnostics["sam"] = {"used_codes": sam_codes}

    if "DIBBS" in sources:
        dibbs_code_results: list[dict[str, Any]] = []
        if dibbs_fsc_codes:
            try:
                dibbs_raw: list[RawOpportunity] = []
                max_pages = int(payload.get("max_pages") or 4)
                for dibbs_fsc in dibbs_fsc_codes:
                    if use_total_result_limit and total_budget_remaining <= 0:
                        dibbs_code_results.append(
                            {
                                "code": dibbs_fsc,
                                "raw_rows": 0,
                                "skipped_reason": "total result limit reached",
                            }
                        )
                        completed_steps += 1
                        _progress("DIBBS", dibbs_fsc, 0)
                        continue
                    code_limit = min(limit, total_budget_remaining) if use_total_result_limit else limit
                    dibbs_payload = {
                        "fsc": dibbs_fsc,
                        "limit": code_limit,
                        "max_pages": max_pages,
                        "all_results": use_all_results,
                    }
                    try:
                        dibbs_code_raw = guarded_fetch_dibbs_opportunities(
                            params=dibbs_payload, max_pages=max_pages
                        )
                    except Exception as exc:
                        dibbs_code_raw = []
                        dibbs_code_results.append(
                            {
                                "code": dibbs_fsc,
                                "raw_rows": 0,
                                "error": str(exc),
                            }
                        )
                        completed_steps += 1
                        _progress("DIBBS", dibbs_fsc, 0)
                        continue
                    completed_steps += 1
                    if use_total_result_limit:
                        dibbs_code_raw = dibbs_code_raw[:total_budget_remaining]
                        total_budget_remaining -= len(dibbs_code_raw)
                    _progress("DIBBS", dibbs_fsc, len(dibbs_code_raw))
                    dibbs_code_results.append(
                        {
                            "code": dibbs_fsc,
                            "raw_rows": len(dibbs_code_raw),
                        }
                    )
                    dibbs_raw.extend(dibbs_code_raw)
                dibbs_raw = _dedupe_raw_opportunities(dibbs_raw)

                if dibbs_raw:
                    dibbs_result = _ingest_many(
                        db,
                        dibbs_raw,
                        auto_enrich_dibbs=_as_bool(payload.get("auto_enrich_parts"), True),
                        queue_nsn_build=_as_bool(payload.get("queue_nsn_build"), False),
                    )
                    dibbs_result["diagnostics"] = {
                        "used_codes": dibbs_fsc_codes,
                        "per_code_limit": limit,
                        "limit_mode": limit_mode,
                        "total_result_limit": total_result_limit if use_total_result_limit else None,
                        "all_results": use_all_results,
                        "raw_rows": len(dibbs_raw),
                        "code_results": dibbs_code_results,
                    }
                else:
                    dibbs_result = {
                        "inserted": 0,
                        "updated": 0,
                        "skipped": 0,
                        "errors": [],
                        "diagnostics": {
                            "used_codes": dibbs_fsc_codes,
                            "per_code_limit": limit,
                            "limit_mode": limit_mode,
                            "total_result_limit": total_result_limit if use_total_result_limit else None,
                            "all_results": use_all_results,
                            "raw_rows": 0,
                            "code_results": dibbs_code_results,
                        },
                    }
                    notices.append("DIBBS returned no opportunities for the FSC code search.")
            except Exception as exc:
                dibbs_result = {
                    "inserted": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [f"DIBBS search failed: {exc}"],
                    "diagnostics": {
                        "used_codes": dibbs_fsc_codes,
                        "per_code_limit": limit,
                    "limit_mode": limit_mode,
                    "total_result_limit": total_result_limit if use_total_result_limit else None,
                    "all_results": use_all_results,
                    "raw_rows": 0,
                    "code_results": dibbs_code_results,
                },
                }
            results["dibbs"] = dibbs_result
        else:
            results["dibbs"] = {
                "inserted": 0,
                "updated": 0,
                "skipped": 0,
                "errors": [],
                "diagnostics": {
                "used_codes": [],
                "per_code_limit": limit,
                "limit_mode": limit_mode,
                "total_result_limit": total_result_limit if use_total_result_limit else None,
                "all_results": use_all_results,
                "raw_rows": 0,
                "code_results": [],
            },
            }
            notices.append("DIBBS search expects FSC codes. Use 4 digits, or enter a longer numeric value and the first 4 digits will be used. You can enter multiple FSCs separated by commas.")
        query_diagnostics["dibbs"] = {"used_codes": dibbs_fsc_codes}

    for result in results.values():
        totals["inserted"] += int(result.get("inserted") or 0)
        totals["updated"] += int(result.get("updated") or 0)
        totals["skipped"] += int(result.get("skipped") or 0)
        totals["errors"].extend(result.get("errors") or [])

    return {
        **totals,
        "sources": results,
        "notices": notices,
        "query": {
            "q": query_text,
            "per_code_limit": limit,
            "limit_mode": limit_mode,
            "total_result_limit": total_result_limit if use_total_result_limit else None,
            "all_results": use_all_results,
            "sources": sources,
        },
        "diagnostics": query_diagnostics,
    }


@router.post("/run")
def run_multi_source_scraper(
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return run_multi_source_search(payload, db, user_id=getattr(current_user, "id", None))
