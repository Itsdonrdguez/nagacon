from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnAwardEvidence
from app.services.nsn_catalog.normalizer import normalize_nsn


def persist_nsn_award_evidence(db: Session, nsn: str, research: dict[str, Any]) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {"created": 0, "updated": 0, "skipped": 0}

    created = 0
    updated = 0
    skipped = 0
    for row in _award_rows(research):
        if not _is_worth_persisting(row):
            skipped += 1
            continue
        values = _values(target.nsn, target.compact, target.fsc, row)
        existing = (
            db.query(NsnAwardEvidence)
            .filter(
                NsnAwardEvidence.compact_nsn == target.compact,
                NsnAwardEvidence.source_system == values["source_system"],
                NsnAwardEvidence.dedupe_key == values["dedupe_key"],
            )
            .first()
        )
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.last_seen_at = datetime.utcnow()
            db.add(existing)
            updated += 1
        else:
            db.add(NsnAwardEvidence(**values))
            created += 1
    if (created or updated) and hasattr(db, "flush"):
        db.flush()
    return {"created": created, "updated": updated, "skipped": skipped}


def summarize_nsn_award_evidence(db: Session, nsn: str, *, limit: int = 25) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {"count": 0, "items": []}
    rows = (
        db.query(NsnAwardEvidence)
        .filter(NsnAwardEvidence.compact_nsn == target.compact)
        .order_by(NsnAwardEvidence.match_score.desc().nullslast(), NsnAwardEvidence.award_date.desc().nullslast())
        .limit(max(min(limit, 100), 1))
        .all()
    )
    amounts = [row.award_amount for row in rows if row.award_amount is not None]
    return {
        "count": len(rows),
        "amount_low": min(amounts) if amounts else None,
        "amount_high": max(amounts) if amounts else None,
        "amount_average": round(sum(amounts) / len(amounts), 2) if amounts else None,
        "top_recipients": _top_counts([row.recipient_name for row in rows]),
        "items": [
            {
                "source_system": row.source_system,
                "award_id": row.award_id,
                "piid": row.piid,
                "recipient_name": row.recipient_name,
                "recipient_cage": row.recipient_cage,
                "award_date": row.award_date,
                "award_amount": row.award_amount,
                "awarding_agency": row.awarding_agency,
                "description": row.description,
                "matched_by": row.matched_by,
                "match_score": row.match_score,
                "match_confidence": row.match_confidence,
                "match_reasons": row.match_reasons,
            }
            for row in rows
        ],
    }


def _award_rows(research: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ["strict_seedable_product_like_awards", "seedable_product_like_awards", "product_like_awards", "awards"]:
        rows.extend(research.get(key) or [])
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("award_id") or "").lower(),
            str(row.get("recipient_name") or "").lower(),
            str(row.get("start_date") or row.get("award_date") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _is_worth_persisting(row: dict[str, Any]) -> bool:
    reasons = " ".join(row.get("relevance_reasons") or []).lower()
    matched_by = str(row.get("matched_by") or "").lower()
    score = float(row.get("relevance_score") or 0)
    if row.get("strict_seedable_product_evidence") or row.get("seedable_product_evidence"):
        return True
    if any(token in reasons for token in ["nsn", "part_number", "catalog_manufacturer"]):
        return True
    if matched_by.startswith(("nsn_only:", "compact_nsn_only:", "part_number")):
        return True
    return score >= 6


def _values(nsn: str, compact_nsn: str, fsc: str, row: dict[str, Any]) -> dict[str, Any]:
    reasons = list(row.get("relevance_reasons") or row.get("match_reasons") or [])
    return {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "fsc": fsc,
        "source_system": "USAspending",
        "dedupe_key": _dedupe_key(row),
        "award_id": _clean(row.get("award_id"), 160) or None,
        "piid": _clean(row.get("piid"), 160) or None,
        "recipient_name": _clean(row.get("recipient_name"), 300) or None,
        "recipient_cage": _clean(row.get("cage") or row.get("recipient_cage"), 20) or None,
        "recipient_uei": _clean(row.get("recipient_uei"), 80) or None,
        "awarding_agency": _clean(row.get("awarding_agency"), 240) or None,
        "award_date": _clean(row.get("start_date") or row.get("award_date"), 40) or None,
        "award_amount": _to_float(row.get("award_amount")),
        "description": _clean(row.get("description")) or None,
        "psc_code": fsc,
        "matched_by": _clean(row.get("matched_by"), 120) or None,
        "match_score": _to_float(row.get("relevance_score")),
        "match_confidence": _confidence_label(_to_float(row.get("relevance_score")), reasons),
        "match_reasons": reasons,
        "raw_payload": row.get("raw") or row,
    }


def _dedupe_key(row: dict[str, Any]) -> str:
    parts = [
        row.get("award_id") or row.get("piid") or "",
        row.get("recipient_name") or "",
        row.get("start_date") or row.get("award_date") or "",
        str(row.get("award_amount") or ""),
    ]
    return "|".join(_clean(part, 80).lower() for part in parts if _clean(part))[:360] or "unknown"


def _clean(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_len] if max_len and text else text


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _confidence_label(score: float | None, reasons: list[str]) -> str:
    text = " ".join(reasons).lower()
    if any(token in text for token in ["nsn", "part_number", "catalog"]):
        return "high"
    if (score or 0) >= 6:
        return "medium"
    return "low"


def _top_counts(values: list[str | None], limit: int = 10) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        key = (value or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]
