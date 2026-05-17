from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnEvidence, NsnInterchangeability, NsnMaster, NsnReference
from app.services.pricing_intelligence import _sam_supplier_for_cage
from app.services.data_exchange import _csv_response

REFERENCE_TYPE_LABELS = {
    "1": "Approved item name or standard reference",
    "3": "Current design control or item reference",
    "5": "Additional manufacturer or distributor reference",
    "P_PART_PICK": "Preferred manufacturer reference",
}

RELATIONSHIP_TYPE_LABELS = {
    "1": "Exact or approved reference",
    "2": "Manufacturer reference",
    "9": "Alternate or related reference",
    "manufacturer_reference": "Manufacturer reference",
}


def _normalize_nsn(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits or None


def _like_value(value: str | None) -> str | None:
    text = str(value or "").strip()
    return f"%{text}%" if text else None


def _master_row(row: NsnMaster) -> dict[str, Any]:
    return {
        "dataset": "master",
        "nsn": row.nsn,
        "compact_nsn": row.compact_nsn,
        "fsc": row.fsc,
        "niin": row.niin,
        "item_name": row.item_name,
        "item_name_code": row.item_name_code,
        "demil_code": row.demil_code,
        "criticality_code": row.criticality_code,
        "source_name": row.source_name,
        "source_version": row.source_version,
    }


def _label_from_map(value: Any, labels: dict[str, str]) -> str | None:
    key = str(value or "").strip()
    if not key:
        return None
    return labels.get(key, key.replace("_", " ").title())


def _sam_match_for_cage(db: Session, cage: str | None) -> dict[str, Any]:
    sam_company_name, sam_website = _sam_supplier_for_cage(db, cage)
    return {
        "sam_company_name": sam_company_name,
        "sam_website": sam_website,
        "sam_match": bool(sam_company_name),
    }


def _reference_row(db: Session, row: NsnReference) -> dict[str, Any]:
    sam_match = _sam_match_for_cage(db, row.cage)
    display_company_name = sam_match.get("sam_company_name") or row.company_name
    return {
        "dataset": "references",
        "nsn": row.nsn,
        "compact_nsn": row.compact_nsn,
        "fsc": row.fsc,
        "niin": row.niin,
        "cage": row.cage,
        "company_name": row.company_name,
        "display_company_name": display_company_name,
        "part_number": row.part_number,
        "reference_type": row.reference_type,
        "reference_type_label": _label_from_map(row.reference_type, REFERENCE_TYPE_LABELS),
        "relationship_type": row.relationship_type,
        "relationship_type_label": _label_from_map(row.relationship_type, RELATIONSHIP_TYPE_LABELS),
        "source_name": row.source_name,
        "source_version": row.source_version,
        "confidence": row.confidence,
        **sam_match,
    }


def _interchangeability_row(row: NsnInterchangeability) -> dict[str, Any]:
    return {
        "dataset": "interchangeability",
        "nsn": row.nsn,
        "compact_nsn": row.compact_nsn,
        "related_nsn": row.related_nsn,
        "related_compact_nsn": row.related_compact_nsn,
        "relationship_type": row.relationship_type,
        "relationship_type_label": _label_from_map(row.relationship_type, RELATIONSHIP_TYPE_LABELS),
        "order_of_use": row.order_of_use,
        "source_name": row.source_name,
        "source_version": row.source_version,
        "confidence": row.confidence,
        "notes": row.notes,
    }


def _evidence_row(row: NsnEvidence) -> dict[str, Any]:
    return {
        "dataset": "evidence",
        "nsn": row.nsn,
        "compact_nsn": row.compact_nsn,
        "claim_type": row.claim_type,
        "claim_value": row.claim_value,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "source_version": row.source_version,
        "matched_by": row.matched_by,
        "confidence": row.confidence,
        "evidence_text": row.evidence_text,
    }


def _source_rank(source_name: Any) -> int:
    source = str(source_name or "").strip().upper()
    if source == "PUB_LOG":
        return 0
    if source.startswith("PUB_LOG_V_"):
        return 1
    return 2


def _reference_row_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _source_rank(row.get("source_name")),
        0 if row.get("company_name") else 1,
        0 if str(row.get("reference_type") or "").strip() == "P_PART_PICK" else 1,
        -(float(row.get("confidence") or 0)),
        str(row.get("part_number") or ""),
    )


def _dedupe_best_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("compact_nsn") or ""),
            str(row.get("cage") or ""),
            str(row.get("part_number") or ""),
        )
        current = best_by_key.get(key)
        if current is None or _reference_row_rank(row) < _reference_row_rank(current):
            best_by_key[key] = row
    return sorted(
        best_by_key.values(),
        key=lambda item: (
            str(item.get("compact_nsn") or ""),
            str(item.get("company_name") or ""),
            str(item.get("part_number") or ""),
        ),
    )


def _manufacturer_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [row for row in rows if row.get("cage")]
    best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in candidates:
        key = (
            str(row.get("compact_nsn") or ""),
            str(row.get("cage") or ""),
        )
        current = best_by_key.get(key)
        if current is None or _reference_row_rank(row) < _reference_row_rank(current):
            best_by_key[key] = row
    output = []
    for row in best_by_key.values():
        output.append(
            {
                **row,
                "candidate_label": row.get("company_name") or row.get("cage"),
                "candidate_quality": "preferred" if str(row.get("reference_type") or "").strip() == "P_PART_PICK" else "supporting",
            }
        )
    return sorted(
        output,
        key=lambda item: (
            str(item.get("compact_nsn") or ""),
            str(item.get("company_name") or ""),
            str(item.get("cage") or ""),
        ),
    )


def search_publog_reference(
    db: Session,
    *,
    dataset: str = "references",
    mode: str = "all",
    q: str | None = None,
    nsn: str | None = None,
    part_number: str | None = None,
    cage: str | None = None,
    fsc: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    dataset_key = str(dataset or "references").strip().lower()
    mode_key = str(mode or "all").strip().lower()
    q_like = _like_value(q)
    nsn_value = _normalize_nsn(nsn)
    part_like = _like_value(part_number)
    cage_like = _like_value(cage)
    fsc_value = str(fsc or "").strip() or None
    capped_limit = max(1, min(int(limit or 100), 1000))

    if dataset_key == "master":
        query = db.query(NsnMaster)
        if nsn_value:
            query = query.filter(NsnMaster.compact_nsn == nsn_value)
        if fsc_value:
            query = query.filter(NsnMaster.fsc == fsc_value)
        if q_like:
            query = query.filter(
                or_(
                    NsnMaster.nsn.ilike(q_like),
                    NsnMaster.compact_nsn.ilike(q_like),
                    NsnMaster.item_name.ilike(q_like),
                )
            )
        rows = query.order_by(NsnMaster.compact_nsn.asc()).limit(capped_limit).all()
        return {"dataset": dataset_key, "mode": mode_key, "rows": [_master_row(row) for row in rows], "total": len(rows)}

    if dataset_key == "interchangeability":
        query = db.query(NsnInterchangeability)
        if nsn_value:
            query = query.filter(NsnInterchangeability.compact_nsn == nsn_value)
        if q_like:
            query = query.filter(
                or_(
                    NsnInterchangeability.nsn.ilike(q_like),
                    NsnInterchangeability.related_nsn.ilike(q_like),
                    NsnInterchangeability.relationship_type.ilike(q_like),
                )
            )
        rows = query.order_by(NsnInterchangeability.compact_nsn.asc()).limit(capped_limit).all()
        return {"dataset": dataset_key, "mode": mode_key, "rows": [_interchangeability_row(row) for row in rows], "total": len(rows)}

    if dataset_key == "evidence":
        query = db.query(NsnEvidence)
        if nsn_value:
            query = query.filter(NsnEvidence.compact_nsn == nsn_value)
        if q_like:
            query = query.filter(
                or_(
                    NsnEvidence.nsn.ilike(q_like),
                    NsnEvidence.claim_type.ilike(q_like),
                    NsnEvidence.claim_value.ilike(q_like),
                    NsnEvidence.evidence_text.ilike(q_like),
                )
            )
        rows = query.order_by(NsnEvidence.compact_nsn.asc()).limit(capped_limit).all()
        return {"dataset": dataset_key, "mode": mode_key, "rows": [_evidence_row(row) for row in rows], "total": len(rows)}

    query = db.query(NsnReference)
    if nsn_value:
        query = query.filter(NsnReference.compact_nsn == nsn_value)
    if part_like:
        query = query.filter(NsnReference.part_number.ilike(part_like))
    if cage_like:
        query = query.filter(
            or_(
                NsnReference.cage.ilike(cage_like),
                NsnReference.company_name.ilike(cage_like),
            )
        )
    if fsc_value:
        query = query.filter(NsnReference.fsc == fsc_value)
    if q_like:
        query = query.filter(
            or_(
                NsnReference.nsn.ilike(q_like),
                NsnReference.compact_nsn.ilike(q_like),
                NsnReference.part_number.ilike(q_like),
                NsnReference.cage.ilike(q_like),
                NsnReference.company_name.ilike(q_like),
            )
        )
    rows = query.order_by(NsnReference.compact_nsn.asc(), NsnReference.part_number.asc()).limit(capped_limit).all()
    output_rows = [_reference_row(db, row) for row in rows]
    if mode_key == "best_rows":
        output_rows = _dedupe_best_rows(output_rows)
    elif mode_key == "manufacturer_candidates":
        output_rows = _manufacturer_candidates(output_rows)
    return {"dataset": "references", "mode": mode_key, "rows": output_rows, "total": len(output_rows)}


def export_publog_reference_csv(
    db: Session,
    *,
    dataset: str = "references",
    mode: str = "all",
    q: str | None = None,
    nsn: str | None = None,
    part_number: str | None = None,
    cage: str | None = None,
    fsc: str | None = None,
    limit: int = 1000,
) -> str:
    result = search_publog_reference(
        db,
        dataset=dataset,
        mode=mode,
        q=q,
        nsn=nsn,
        part_number=part_number,
        cage=cage,
        fsc=fsc,
        limit=limit,
    )
    rows = result.get("rows") or []
    fieldnames = list(rows[0].keys()) if rows else ["dataset", "nsn", "compact_nsn"]
    return _csv_response(rows, fieldnames)


def export_publog_reference_json(
    db: Session,
    *,
    dataset: str = "references",
    mode: str = "all",
    q: str | None = None,
    nsn: str | None = None,
    part_number: str | None = None,
    cage: str | None = None,
    fsc: str | None = None,
    limit: int = 1000,
) -> str:
    result = search_publog_reference(
        db,
        dataset=dataset,
        mode=mode,
        q=q,
        nsn=nsn,
        part_number=part_number,
        cage=cage,
        fsc=fsc,
        limit=limit,
    )
    return json.dumps(result, default=str)
