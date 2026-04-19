from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.nsn_catalog import (
    NsnCatalogImportRun,
    NsnInterchangeability,
    NsnMaster,
    NsnReference,
)
from app.services.nsn_catalog.normalizer import clean_part_number, normalize_cage, normalize_nsn


HEADER_ALIASES = {
    "nsn": {
        "nsn",
        "nationalstocknumber",
        "nationalstocknum",
        "nationalstockno",
        "stocknumber",
        "stocknum",
    },
    "fsc": {"fsc", "fsgfsc", "federal supply class", "federal supply classification"},
    "niin": {"niin", "nationalitemidentificationnumber", "nationalitemidnumber"},
    "item_name": {"itemname", "item_name", "nomenclature", "noun", "nounname", "itemdescription"},
    "item_name_code": {"inc", "itemnamecode", "item_name_code"},
    "demil_code": {"demil", "demilcode", "demilitarizationcode"},
    "criticality_code": {"criticality", "criticalitycode", "ciic", "ciiccode"},
    "cage": {"cage", "cagecode", "ncage", "manufacturercage", "mfrcage"},
    "company_name": {"company", "companyname", "manufacturer", "manufacturername", "mfr", "mfrname"},
    "part_number": {"partnumber", "partno", "pn", "referencenumber", "reference_number", "refnum"},
    "reference_type": {"referencetype", "reference_type", "rncc", "rnvc"},
    "relationship_type": {"relationshiptype", "relationship_type", "sourceofcontrol", "sos"},
    "related_nsn": {"relatednsn", "related_nsn", "substitutensn", "interchangeablensn", "replacingnsn"},
    "order_of_use": {"orderofuse", "order_of_use", "oou"},
}


@dataclass(frozen=True)
class PublogRow:
    nsn: str
    compact_nsn: str
    fsc: str
    niin: str
    item_name: str | None = None
    item_name_code: str | None = None
    demil_code: str | None = None
    criticality_code: str | None = None
    cage: str | None = None
    company_name: str | None = None
    part_number: str | None = None
    reference_type: str | None = None
    relationship_type: str | None = None
    related_nsn: str | None = None
    related_compact_nsn: str | None = None
    order_of_use: str | None = None
    raw_payload: dict[str, Any] | None = None


def _header_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").strip().lower())


def _clean(value: Any, max_len: int | None = None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return None
    return text[:max_len] if max_len else text


def _alias_map(headers: Iterable[str]) -> dict[str, str]:
    normalized_headers = {_header_key(header): header for header in headers}
    out: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            key = _header_key(alias)
            if key in normalized_headers:
                out[canonical] = normalized_headers[key]
                break
    return out


def _value(row: dict[str, Any], aliases: dict[str, str], field: str, max_len: int | None = None) -> str | None:
    header = aliases.get(field)
    return _clean(row.get(header), max_len=max_len) if header else None


def parse_publog_csv(path: str | Path, *, limit: int | None = None) -> list[PublogRow]:
    rows: list[PublogRow] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        aliases = _alias_map(reader.fieldnames or [])
        for raw in reader:
            parsed = parse_publog_row(raw, aliases)
            if parsed:
                rows.append(parsed)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def parse_publog_row(raw: dict[str, Any], aliases: dict[str, str] | None = None) -> PublogRow | None:
    aliases = aliases or _alias_map(raw.keys())
    nsn_value = _value(raw, aliases, "nsn")
    if not nsn_value:
        fsc = re.sub(r"\D+", "", _value(raw, aliases, "fsc") or "")
        niin = re.sub(r"\D+", "", _value(raw, aliases, "niin") or "")
        if len(fsc) >= 4 and len(niin) >= 9:
            nsn_value = f"{fsc[:4]}{niin[:9]}"
    target = normalize_nsn(nsn_value)
    if not target:
        return None

    related_target = normalize_nsn(_value(raw, aliases, "related_nsn"))
    cage = normalize_cage(_value(raw, aliases, "cage", 20)) or None
    part_number = clean_part_number(_value(raw, aliases, "part_number", 160)) or None

    return PublogRow(
        nsn=target.nsn,
        compact_nsn=target.compact,
        fsc=target.fsc,
        niin=target.niin,
        item_name=_value(raw, aliases, "item_name", 300),
        item_name_code=_value(raw, aliases, "item_name_code", 20),
        demil_code=_value(raw, aliases, "demil_code", 20),
        criticality_code=_value(raw, aliases, "criticality_code", 20),
        cage=cage,
        company_name=_value(raw, aliases, "company_name", 300),
        part_number=part_number,
        reference_type=_value(raw, aliases, "reference_type", 80),
        relationship_type=_value(raw, aliases, "relationship_type", 80),
        related_nsn=related_target.nsn if related_target else None,
        related_compact_nsn=related_target.compact if related_target else None,
        order_of_use=_value(raw, aliases, "order_of_use", 40),
        raw_payload={str(k): v for k, v in raw.items()},
    )


def import_publog_csv(
    db: Session,
    path: str | Path,
    *,
    source_name: str = "PUB_LOG",
    source_version: str | None = None,
    commit_every: int = 1000,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    file_path = Path(path)
    run = NsnCatalogImportRun(
        source_name=source_name,
        source_version=source_version,
        source_file=str(file_path),
        status="running",
        started_at=datetime.utcnow(),
        metadata_json={"dry_run": dry_run},
    )
    if not dry_run:
        db.add(run)
        db.commit()
        db.refresh(run)

    rows_seen = 0
    rows_imported = 0
    master_count = 0
    reference_count = 0
    interchange_count = 0
    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            aliases = _alias_map(reader.fieldnames or [])
            for raw in reader:
                rows_seen += 1
                parsed = parse_publog_row(raw, aliases)
                if not parsed:
                    continue
                rows_imported += 1
                if not dry_run:
                    master_created = _upsert_master(db, parsed, source_name=source_name, source_version=source_version)
                    master_count += int(master_created)
                    if parsed.cage or parsed.part_number:
                        reference_created = _upsert_reference(db, parsed, source_name=source_name, source_version=source_version)
                        reference_count += int(reference_created)
                    if parsed.related_nsn and parsed.related_compact_nsn:
                        interchange_created = _upsert_interchange(db, parsed, source_name=source_name, source_version=source_version)
                        interchange_count += int(interchange_created)
                    if rows_imported % max(commit_every, 1) == 0:
                        db.commit()
                if limit is not None and rows_seen >= limit:
                    break
        if not dry_run:
            run.status = "completed"
            run.rows_seen = rows_seen
            run.rows_imported = rows_imported
            run.completed_at = datetime.utcnow()
            run.metadata_json = {
                "dry_run": dry_run,
                "masters_created": master_count,
                "references_created": reference_count,
                "interchanges_created": interchange_count,
            }
            db.add(run)
            db.commit()
    except Exception as exc:
        if not dry_run:
            db.rollback()
            run.status = "failed"
            run.rows_seen = rows_seen
            run.rows_imported = rows_imported
            run.error = str(exc)
            run.completed_at = datetime.utcnow()
            db.add(run)
            db.commit()
        raise

    return {
        "source_name": source_name,
        "source_version": source_version,
        "source_file": str(file_path),
        "dry_run": dry_run,
        "rows_seen": rows_seen,
        "rows_imported": rows_imported,
        "masters_created": master_count,
        "references_created": reference_count,
        "interchanges_created": interchange_count,
        "import_run_id": None if dry_run else run.id,
    }


def _upsert_master(db: Session, row: PublogRow, *, source_name: str, source_version: str | None) -> bool:
    existing = db.query(NsnMaster).filter(NsnMaster.compact_nsn == row.compact_nsn).first()
    if existing:
        _fill(existing, "item_name", row.item_name)
        _fill(existing, "item_name_code", row.item_name_code)
        _fill(existing, "demil_code", row.demil_code)
        _fill(existing, "criticality_code", row.criticality_code)
        existing.source_name = existing.source_name or source_name
        existing.source_version = existing.source_version or source_version
        if not existing.raw_payload and row.raw_payload:
            existing.raw_payload = row.raw_payload
        db.add(existing)
        return False
    db.add(
        NsnMaster(
            nsn=row.nsn,
            compact_nsn=row.compact_nsn,
            fsc=row.fsc,
            niin=row.niin,
            item_name=row.item_name,
            item_name_code=row.item_name_code,
            demil_code=row.demil_code,
            criticality_code=row.criticality_code,
            public_data_status="public",
            source_name=source_name,
            source_version=source_version,
            raw_payload=row.raw_payload,
        )
    )
    return True


def _upsert_reference(db: Session, row: PublogRow, *, source_name: str, source_version: str | None) -> bool:
    existing = (
        db.query(NsnReference)
        .filter(
            NsnReference.compact_nsn == row.compact_nsn,
            NsnReference.cage == row.cage,
            NsnReference.part_number == row.part_number,
            NsnReference.source_name == source_name,
        )
        .first()
    )
    if existing:
        _fill(existing, "company_name", row.company_name)
        _fill(existing, "reference_type", row.reference_type)
        _fill(existing, "relationship_type", row.relationship_type)
        _fill(existing, "source_version", source_version)
        if not existing.raw_payload and row.raw_payload:
            existing.raw_payload = row.raw_payload
        db.add(existing)
        return False
    db.add(
        NsnReference(
            nsn=row.nsn,
            compact_nsn=row.compact_nsn,
            fsc=row.fsc,
            niin=row.niin,
            cage=row.cage,
            company_name=row.company_name,
            part_number=row.part_number,
            reference_type=row.reference_type,
            relationship_type=row.relationship_type or "reference",
            source_name=source_name,
            source_version=source_version,
            confidence=0.9,
            raw_payload=row.raw_payload,
        )
    )
    return True


def _upsert_interchange(db: Session, row: PublogRow, *, source_name: str, source_version: str | None) -> bool:
    existing = (
        db.query(NsnInterchangeability)
        .filter(
            NsnInterchangeability.compact_nsn == row.compact_nsn,
            NsnInterchangeability.related_compact_nsn == row.related_compact_nsn,
            NsnInterchangeability.relationship_type == (row.relationship_type or "interchangeability"),
            NsnInterchangeability.source_name == source_name,
        )
        .first()
    )
    if existing:
        _fill(existing, "order_of_use", row.order_of_use)
        _fill(existing, "source_version", source_version)
        if not existing.raw_payload and row.raw_payload:
            existing.raw_payload = row.raw_payload
        db.add(existing)
        return False
    db.add(
        NsnInterchangeability(
            nsn=row.nsn,
            compact_nsn=row.compact_nsn,
            related_nsn=row.related_nsn or "",
            related_compact_nsn=row.related_compact_nsn or "",
            relationship_type=row.relationship_type or "interchangeability",
            order_of_use=row.order_of_use,
            source_name=source_name,
            source_version=source_version,
            confidence=0.85,
            raw_payload=row.raw_payload,
        )
    )
    return True


def _fill(target: Any, field: str, value: Any) -> None:
    if value and not getattr(target, field, None):
        setattr(target, field, value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import PUB LOG-style CSV data into the NSN catalog tables.")
    parser.add_argument("csv_path", help="Path to a PUB LOG-style CSV file.")
    parser.add_argument("--source-name", default="PUB_LOG")
    parser.add_argument("--source-version", default=None)
    parser.add_argument("--commit-every", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = import_publog_csv(
            db,
            args.csv_path,
            source_name=args.source_name,
            source_version=args.source_version,
            commit_every=args.commit_every,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(result)
    except IntegrityError:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
