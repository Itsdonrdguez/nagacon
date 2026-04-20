from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.part_finder import find_part_for_opportunity
from app.services.workspace_service import create_artifact


def enrich_dibbs_opportunities_after_ingest(
    db: Session,
    opportunity_ids: list[int],
    *,
    organization_id: int | None = None,
    max_items: int = 25,
    queue_nsn_build: bool = False,
) -> dict[str, Any]:
    seen: set[int] = set()
    ids = []
    for opportunity_id in opportunity_ids:
        try:
            clean_id = int(opportunity_id)
        except (TypeError, ValueError):
            continue
        if clean_id in seen:
            continue
        seen.add(clean_id)
        ids.append(clean_id)
        if len(ids) >= max_items:
            break

    items: list[dict[str, Any]] = []
    queued_jobs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for opportunity_id in ids:
        try:
            result = find_part_for_opportunity(db, opportunity_id, organization_id=organization_id)
            artifact = _persist_part_finder_artifact(db, opportunity_id, result)
            item = {
                "opportunity_id": opportunity_id,
                "status": result.get("status"),
                "nsn": (result.get("part") or {}).get("nsn"),
                "quantity": (result.get("part") or {}).get("quantity"),
                "item_name": (result.get("part") or {}).get("item_name"),
                "artifact_id": getattr(artifact, "id", None),
            }
            if queue_nsn_build and item["nsn"]:
                from app.services.search_jobs import start_search_job

                job = start_search_job(
                    "nsn_build",
                    {
                        "nsn": item["nsn"],
                        "organization_id": organization_id,
                        "seed_providers": True,
                        "run_usaspending": True,
                        "limit": 50,
                        "source": "dibbs_ingest_auto_enrichment",
                    },
                )
                item["nsn_build_job_id"] = job.get("id")
                queued_jobs.append({"opportunity_id": opportunity_id, "nsn": item["nsn"], "job_id": job.get("id")})
            items.append(item)
        except Exception as exc:
            db.rollback()
            errors.append({"opportunity_id": opportunity_id, "error": f"{exc.__class__.__name__}: {exc}"})

    return {
        "status": "completed_with_errors" if errors else "completed",
        "requested": len(opportunity_ids),
        "processed": len(items),
        "queued_nsn_build_jobs": queued_jobs,
        "errors": errors,
        "items": items,
    }


def _persist_part_finder_artifact(db: Session, opportunity_id: int, result: dict[str, Any]):
    part = dict(result.get("part") or {})
    opportunity = dict(result.get("opportunity") or {})
    title_key = opportunity.get("solicitation_number") or part.get("nsn") or opportunity_id
    return create_artifact(
        db,
        opportunity_id,
        "PART_FINDER",
        f"Part Finder - {title_key}",
        content_json=_json_safe(
            {
                "part_finder": {
                    "status": result.get("status"),
                    "part": part,
                    "providers": list(result.get("providers") or [])[:10],
                    "awardees": list(result.get("awardees") or [])[:10],
                    "evidence": result.get("evidence") or {},
                    "confidence": result.get("confidence") or {},
                    "next_actions": result.get("next_actions") or [],
                    "generated_at": datetime.utcnow().isoformat(),
                    "source": "dibbs_ingest_auto_enrichment",
                }
            }
        ),
        replace_existing=True,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
