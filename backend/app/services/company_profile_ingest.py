from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.company_profile import CompanyProfile
from app.schemas.opportunity import RawOpportunity
from app.services.ingest_enrichment import enrich_dibbs_opportunities_after_ingest
from app.services.opportunity_ingest import find_existing_opportunity
from app.services.opportunity_ingest import upsert_raw_opportunity
from app.services.provider_settings_service import get_effective_sam_api_key
from app.services.scrapers.dibbs_scraper import fetch_dibbs_opportunities
from app.services.scrapers.sam_scraper import SamScraperError, fetch_sam_opportunities

DEFAULT_DIBBS_FSC_CODES = [
    "6520",
    "8470",
    "6550",
    "5805",
    "5130",
    "5810",
    "5998",
    "5999",
    "1095",
    "6110",
    "6515",
]

DEFAULT_SAM_NAICS_CODES = [
    "561720",
    "561210",
    "561730",
    "561740",
    "561790",
    "484110",
    "484121",
    "484122",
    "488510",
    "492110",
    "492210",
    "485999",
    "488999",
]

DEFAULT_SAM_KEYWORDS = [
    "janitorial",
    "custodial",
    "cleaning",
    "facilities support",
    "transportation",
    "freight",
    "trucking",
    "logistics",
    "courier",
    "delivery",
]

QUICK_SEARCH_RESULTS_PER_CODE = 25


def _clean_list(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if not item:
            continue
        key = item.upper()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def get_company_ingest_preferences(profile: CompanyProfile | None) -> dict[str, Any]:
    profile = profile or CompanyProfile(legal_name="Default Company")
    return {
        "preferred_dibbs_fsc_codes": _clean_list(getattr(profile, "preferred_dibbs_fsc_codes", None)) or list(DEFAULT_DIBBS_FSC_CODES),
        "preferred_sam_naics_codes": _clean_list(getattr(profile, "preferred_sam_naics_codes", None)) or list(DEFAULT_SAM_NAICS_CODES),
        "preferred_sam_keywords": _clean_list(getattr(profile, "preferred_sam_keywords", None)) or list(DEFAULT_SAM_KEYWORDS),
        "preferred_sam_agencies": _clean_list(getattr(profile, "preferred_sam_agencies", None)),
        "preferred_sam_states": _clean_list(getattr(profile, "preferred_sam_states", None))
        or ([getattr(profile, "state")] if getattr(profile, "state", None) else []),
        "auto_ingest_enabled": bool(getattr(profile, "auto_ingest_enabled", False)),
        "auto_ingest_limit": int(getattr(profile, "auto_ingest_limit", None) or 25),
        "auto_ingest_interval_hours": int(getattr(profile, "auto_ingest_interval_hours", None) or 24),
        "dibbs_pdf_download_limit": int(getattr(profile, "dibbs_pdf_download_limit", None) or 25),
        "last_auto_ingest_at": getattr(profile, "last_auto_ingest_at", None).isoformat() if getattr(profile, "last_auto_ingest_at", None) else None,
    }


def build_company_ingest_plan(profile: CompanyProfile | None) -> dict[str, Any]:
    prefs = get_company_ingest_preferences(profile)
    sam_queries = []
    if prefs["preferred_sam_naics_codes"]:
        for naics_code in prefs["preferred_sam_naics_codes"]:
            query = {
                "ncode": naics_code,
                "limit": prefs["auto_ingest_limit"],
            }
            if prefs["preferred_sam_states"]:
                query["state"] = prefs["preferred_sam_states"][0]
            if prefs["preferred_sam_agencies"]:
                query["organizationName"] = prefs["preferred_sam_agencies"][0]
            sam_queries.append(query)
    else:
        for keyword in prefs["preferred_sam_keywords"]:
            query = {
                "title": keyword,
                "limit": prefs["auto_ingest_limit"],
            }
            if prefs["preferred_sam_states"]:
                query["state"] = prefs["preferred_sam_states"][0]
            if prefs["preferred_sam_agencies"]:
                query["organizationName"] = prefs["preferred_sam_agencies"][0]
            sam_queries.append(query)

    return {
        "auto_ingest_enabled": prefs["auto_ingest_enabled"],
        "auto_ingest_limit": prefs["auto_ingest_limit"],
        "auto_ingest_interval_hours": prefs["auto_ingest_interval_hours"],
        "last_auto_ingest_at": prefs["last_auto_ingest_at"],
        "dibbs_pdf_download_limit": prefs["dibbs_pdf_download_limit"],
        "dibbs": {
            "fsc_codes": prefs["preferred_dibbs_fsc_codes"],
            "per_code_limit": prefs["auto_ingest_limit"],
            "pdf_download_limit": prefs["dibbs_pdf_download_limit"],
        },
        "sam": {
            "naics_codes": prefs["preferred_sam_naics_codes"],
            "per_naics_limit": prefs["auto_ingest_limit"],
            "keywords": prefs["preferred_sam_keywords"],
            "agencies": prefs["preferred_sam_agencies"],
            "states": prefs["preferred_sam_states"],
            "queries": sam_queries,
        },
    }


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


def _ingest_many(
    db: Session,
    raw_opps: list[RawOpportunity],
    *,
    organization_id: int | None = None,
    collect_dibbs_ids: bool = False,
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
            if collect_dibbs_ids and str(raw.source or "").upper() == "DIBBS":
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
    if collect_dibbs_ids:
        out["dibbs_opportunity_ids"] = dibbs_opportunity_ids
    return out


def _filter_sam_by_naics(raw_opps: list[RawOpportunity], allowed_naics: list[str]) -> list[RawOpportunity]:
    if not allowed_naics:
        return raw_opps
    allowed = {str(code).strip() for code in allowed_naics if str(code).strip()}
    if not allowed:
        return raw_opps
    return [raw for raw in raw_opps if (raw.naics_code or "").strip() in allowed]


def _build_effective_plan(plan: dict[str, Any], quick: bool) -> dict[str, Any]:
    if not quick:
        return plan

    effective_plan = {
        **plan,
        "search_mode": "quick",
        "auto_ingest_limit": min(int(plan.get("auto_ingest_limit") or 25), QUICK_SEARCH_RESULTS_PER_CODE),
        "dibbs": {
            **(plan.get("dibbs") or {}),
            "per_code_limit": QUICK_SEARCH_RESULTS_PER_CODE,
        },
        "sam": {
            **(plan.get("sam") or {}),
            "per_naics_limit": QUICK_SEARCH_RESULTS_PER_CODE,
        },
    }
    for query in effective_plan["sam"]["queries"]:
        query["limit"] = QUICK_SEARCH_RESULTS_PER_CODE
    return effective_plan


def run_company_profile_ingest(
    db: Session,
    profile: CompanyProfile | None,
    quick: bool = False,
    update_last_run: bool = True,
    progress_callback=None,
    user_id: int | None = None,
) -> dict[str, Any]:
    plan = build_company_ingest_plan(profile)
    plan = _build_effective_plan(plan, quick=quick)
    limit = int(plan["auto_ingest_limit"] or 25)
    total_steps = len(plan["dibbs"]["fsc_codes"]) + len(plan["sam"]["queries"])
    completed_steps = 0

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

    _progress("Search", "Preparing saved search", None)

    dibbs_raw: list[RawOpportunity] = []
    dibbs_results: list[dict[str, Any]] = []
    dibbs_errors: list[str] = []
    for fsc_code in plan["dibbs"]["fsc_codes"]:
        try:
            rows = fetch_dibbs_opportunities({"fsc": fsc_code, "limit": limit, "max_pages": 4}, max_pages=4)
        except Exception as exc:
            rows = []
            dibbs_errors.append(f"FSC {fsc_code}: {exc}")
            dibbs_results.append({"code": fsc_code, "raw_rows": 0, "error": str(exc)})
            completed_steps += 1
            _progress("DIBBS", fsc_code, 0)
            continue
        completed_steps += 1
        _progress("DIBBS", fsc_code, len(rows))
        dibbs_results.append({"code": fsc_code, "raw_rows": len(rows)})
        dibbs_raw.extend(rows)
    dibbs_raw = _dedupe_raw_opportunities(dibbs_raw)
    organization_id = getattr(profile, "organization_id", None) if profile is not None else None
    dibbs_ingest = _ingest_many(db, dibbs_raw, organization_id=organization_id, collect_dibbs_ids=True)
    dibbs_ids = list(dibbs_ingest.pop("dibbs_opportunity_ids", []) or [])
    if dibbs_ids:
        dibbs_ingest["part_finder_enrichment"] = enrich_dibbs_opportunities_after_ingest(
            db,
            dibbs_ids,
            organization_id=organization_id,
            queue_nsn_build=False,
            max_items=len(dibbs_ids),
        )
    dibbs_ingest["errors"] = list(dict.fromkeys((dibbs_ingest.get("errors") or []) + dibbs_errors))
    dibbs_ingest["diagnostics"] = {
        "used_codes": plan["dibbs"]["fsc_codes"],
        "per_code_limit": limit,
        "raw_rows": len(dibbs_raw),
        "code_results": dibbs_results,
    }

    sam_raw: list[RawOpportunity] = []
    sam_results: list[dict[str, Any]] = []
    sam_errors: list[str] = []
    sam_api_key = get_effective_sam_api_key(db, user_id=user_id)
    for query in plan["sam"]["queries"]:
        try:
            effective_query = dict(query)
            if sam_api_key:
                effective_query["api_key"] = sam_api_key
            rows = fetch_sam_opportunities(effective_query)
            filtered_rows = _filter_sam_by_naics(rows, plan["sam"]["naics_codes"])
            completed_steps += 1
            _progress("SAM", query.get("ncode") or query.get("title") or "SAM", len(filtered_rows))
            sam_results.append(
                {
                    "query": query,
                    "naics_code": query.get("ncode"),
                    "raw_rows": len(rows),
                    "naics_filtered_rows": len(filtered_rows),
                }
            )
            sam_raw.extend(filtered_rows)
        except SamScraperError as exc:
            completed_steps += 1
            _progress("SAM", query.get("ncode") or query.get("title") or "SAM", 0)
            sam_results.append({"query": query, "raw_rows": 0, "naics_filtered_rows": 0, "error": str(exc)})
            sam_errors.append(str(exc))
    sam_raw = _dedupe_raw_opportunities(sam_raw)
    sam_ingest = _ingest_many(db, sam_raw, organization_id=organization_id)
    sam_ingest["errors"] = list(dict.fromkeys((sam_ingest.get("errors") or []) + sam_errors))
    sam_ingest["diagnostics"] = {
        "queries": sam_results,
        "raw_rows": len(sam_raw),
        "naics_codes": plan["sam"]["naics_codes"],
        "per_naics_limit": plan["sam"].get("per_naics_limit"),
        "keywords": plan["sam"]["keywords"],
        "agencies": plan["sam"]["agencies"],
        "states": plan["sam"]["states"],
    }

    if profile is not None and update_last_run:
        profile.last_auto_ingest_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return {
        "search_mode": plan.get("search_mode") or "full",
        "plan": plan,
        "results": {
            "dibbs": dibbs_ingest,
            "sam": sam_ingest,
        },
    }


def company_profile_due_for_auto_ingest(profile: CompanyProfile | None, now: datetime | None = None) -> bool:
    if not profile or not getattr(profile, "auto_ingest_enabled", False):
        return False
    current_time = now or datetime.utcnow()
    interval_hours = int(getattr(profile, "auto_ingest_interval_hours", None) or 24)
    last_run = getattr(profile, "last_auto_ingest_at", None)
    if not last_run:
        return True
    return last_run <= current_time - timedelta(hours=interval_hours)
