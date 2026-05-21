from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.nsn_catalog import NsnEvidence, NsnInterchangeability, NsnMaster, NsnReference
from app.services.nsn_catalog.normalizer import normalize_cage, normalize_nsn


BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLOG_DIR = BACKEND_ROOT / "publog_work"
DEFAULT_PUBLOG_ZIP = BACKEND_ROOT / "PublogDVD.zip"
REQUIRED_PUBLOG_FILES = [
    "IMD.LST",
    "IMD_1OF1.TXT",
    "TOOLS/UTILITIES/Decomp.exe",
    "P_FLIS_NSN.TAB",
    "P_PART_PICK.TAB",
    "P_CAGE.TAB",
    "V_FLIS_PART.TAB",
    "V_CHARACTERISTICS.TAB",
    "V_H6_RELATED.TAB",
]


def ensure_publog_workdir(
    *,
    zip_path: str | Path | None = None,
    publog_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(publog_dir or os.getenv("PUBLOG_DATA_DIR") or DEFAULT_PUBLOG_DIR)
    archive_path = Path(zip_path or os.getenv("PUBLOG_DVD_ZIP") or DEFAULT_PUBLOG_ZIP)
    root.mkdir(parents=True, exist_ok=True)

    required_targets = [root / Path(name).name for name in REQUIRED_PUBLOG_FILES]
    missing_targets = [target for target in required_targets if not target.exists()]
    if not missing_targets:
        return {
            "status": "ready",
            "publog_dir": str(root),
            "zip_path": str(archive_path),
            "extracted": [],
            "missing": [],
        }
    if not archive_path.exists():
        return {
            "status": "missing_zip",
            "publog_dir": str(root),
            "zip_path": str(archive_path),
            "extracted": [],
            "missing": [str(target) for target in missing_targets],
        }

    extracted: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        for name in REQUIRED_PUBLOG_FILES:
            if name not in names:
                continue
            target = root / Path(name).name
            if target.exists():
                continue
            with archive.open(name) as source, target.open("wb") as dest:
                dest.write(source.read())
            extracted.append(str(target))
    missing = [str(target) for target in required_targets if not target.exists()]
    return {
        "status": "ready" if not missing else "missing_files",
        "publog_dir": str(root),
        "zip_path": str(archive_path),
        "extracted": extracted,
        "missing": missing,
    }


def parse_decomp_output(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    header_index = None
    for index, line in enumerate(lines):
        if "|" in line and not line.startswith("-") and not line.lower().startswith("select "):
            header_index = index
            break
    if header_index is None:
        return []
    headers = [part.strip() for part in lines[header_index].split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1:]:
        if "|" not in line:
            continue
        values = [part.strip() for part in line.split("|")]
        if len(values) < len(headers):
            values.extend([""] * (len(headers) - len(values)))
        rows.append(dict(zip(headers, values)))
    return rows


def run_decomp_query(publog_dir: str | Path, sql: str) -> list[dict[str, str]]:
    root = Path(publog_dir)
    exe = root / "Decomp.exe"
    if not exe.exists():
        raise FileNotFoundError(f"Decomp.exe not found in {root}")
    with tempfile.NamedTemporaryFile(prefix="publog_", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [str(exe), str(root), sql, str(output_path)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        rows = parse_decomp_output(output_path.read_text(encoding="utf-8", errors="replace"))
        stdout = completed.stdout or ""
        if completed.returncode != 0 and not rows and "0 rows...done" not in stdout:
            raise RuntimeError(completed.stderr or completed.stdout or f"Decomp exited with {completed.returncode}")
        return rows
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def import_publog_nsn(
    db: Session,
    nsn: str,
    *,
    publog_dir: str | Path | None = None,
    source_version: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    target = normalize_nsn(nsn)
    if not target:
        return {"status": "invalid_nsn", "error": "NSN must contain exactly 13 digits."}

    root = Path(publog_dir or os.getenv("PUBLOG_DATA_DIR") or DEFAULT_PUBLOG_DIR)
    prep = ensure_publog_workdir(publog_dir=root)
    if prep["status"] != "ready":
        return {
            "status": prep["status"],
            "error": "PUB LOG working files are not available.",
            **prep,
        }
    source_version = source_version or _read_publog_version(root)

    nsn_rows = run_decomp_query(
        root,
        f"select FSC,NIIN,INC,ITEM_NAME,SOS from P_FLIS_NSN WHERE NIIN='{target.niin}'",
    )
    part_rows = run_decomp_query(
        root,
        f"select FSC,NIIN,ITEM_NAME,CAGE_CODE,PART_NUMBER,COMPANY_NAME from P_PART_PICK WHERE NIIN='{target.niin}'",
    )
    flis_part_rows = run_decomp_query(
        root,
        f"select NIIN,CAGE_CODE,PART_NUMBER,RNCC,RNVC,RNJC,RNSC,RNAAC from V_FLIS_PART WHERE NIIN='{target.niin}'",
    )
    characteristic_rows = run_decomp_query(
        root,
        f"select NIIN,REQUIREMENTS_STATEMENT,MRC,CLEAR_TEXT_REPLY from V_CHARACTERISTICS WHERE NIIN='{target.niin}'",
    )
    cage_rows = _query_cage_profiles(root, part_rows)
    related_rows = _query_related_item_concepts(root, nsn_rows)
    resolved_related_nsn_rows = _query_resolved_related_nsns(root, target.compact, related_rows)

    master_created = False
    references_created = 0
    references_updated = 0
    evidence_created = 0
    evidence_updated = 0
    interchange_created = 0
    interchange_updated = 0
    if not dry_run:
        if nsn_rows:
            master_created = _upsert_master(db, target.nsn, target.compact, nsn_rows[0], source_version)
        for row in part_rows:
            created = _upsert_reference(db, target.nsn, target.compact, row, source_version)
            references_created += int(created)
            references_updated += int(not created)
        for row in flis_part_rows:
            created = _upsert_flis_part_reference(db, target.nsn, target.compact, target.fsc, row, source_version)
            references_created += int(created)
            references_updated += int(not created)
        for row in cage_rows:
            changed = _upsert_cage_evidence(db, target.nsn, target.compact, row, source_version)
            evidence_created += int(changed)
        for row in characteristic_rows:
            created = _upsert_characteristic_evidence(db, target.nsn, target.compact, row, source_version)
            evidence_created += int(created)
            evidence_updated += int(not created)
        for row in related_rows:
            created = _upsert_related_item_concept(db, target.nsn, target.compact, row, source_version)
            evidence_created += int(created)
            evidence_updated += int(not created)
            created_interchange = _upsert_related_interchange(db, target.nsn, target.compact, row, source_version)
            interchange_created += int(created_interchange)
            interchange_updated += int(not created_interchange)
        for row in resolved_related_nsn_rows:
            _upsert_master(
                db,
                row["related_nsn"],
                row["related_compact_nsn"],
                {
                    "FSC": row.get("related_fsc"),
                    "NIIN": row.get("related_niin"),
                    "INC": row.get("related_inc"),
                    "ITEM_NAME": row.get("related_item_name"),
                },
                source_version,
            )
            created = _upsert_related_nsn_evidence(db, target.nsn, target.compact, row, source_version)
            evidence_created += int(created)
            evidence_updated += int(not created)
            created_interchange = _upsert_resolved_related_interchange(db, target.nsn, target.compact, row, source_version)
            interchange_created += int(created_interchange)
            interchange_updated += int(not created_interchange)
        db.commit()

    return {
        "status": "ok",
        "nsn": target.nsn,
        "compact_nsn": target.compact,
        "fsc": target.fsc,
        "niin": target.niin,
        "publog_dir": str(root),
        "prep": prep,
        "source_version": source_version,
        "dry_run": dry_run,
        "identity_rows": len(nsn_rows),
        "part_rows": len(part_rows),
        "flis_part_rows": len(flis_part_rows),
        "characteristic_rows": len(characteristic_rows),
        "cage_rows": len(cage_rows),
        "related_rows": len(related_rows),
        "resolved_related_nsn_rows": len(resolved_related_nsn_rows),
        "master_created": master_created,
        "references_created": references_created,
        "references_updated": references_updated,
        "evidence_created": evidence_created,
        "evidence_updated": evidence_updated,
        "interchanges_created": interchange_created,
        "interchanges_updated": interchange_updated,
        "identity_sample": nsn_rows[:1],
        "part_samples": part_rows[:10],
        "flis_part_samples": flis_part_rows[:10],
        "characteristic_samples": characteristic_rows[:10],
        "cage_samples": cage_rows[:10],
        "related_samples": related_rows[:10],
        "resolved_related_nsn_samples": resolved_related_nsn_rows[:10],
    }


def _query_cage_profiles(root: Path, part_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    cages = sorted({normalize_cage(row.get("CAGE_CODE")) for row in part_rows if normalize_cage(row.get("CAGE_CODE"))})
    rows: list[dict[str, str]] = []
    for cage in cages[:50]:
        try:
            rows.extend(
                run_decomp_query(
                    root,
                    f"select COUNTRY,STATE_PROVINCE,CAGE_STATUS,CAO,CITY,TYPE,CAGE_CODE,ZIP_POSTAL_ZONE,COMPANY from P_CAGE WHERE CAGE_CODE='{cage}'",
                )
            )
        except Exception:
            continue
    return rows


def _query_related_item_concepts(root: Path, nsn_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not nsn_rows:
        return []
    inc = (nsn_rows[0].get("INC") or "").strip()
    if not inc:
        return []
    try:
        return run_decomp_query(
            root,
            f"select INC,ITEM_NAME,RELATED_INC from V_H6_RELATED WHERE INC='{inc}'",
        )
    except Exception:
        return []


def _query_resolved_related_nsns(root: Path, compact_nsn: str, related_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    related_incs = sorted({(row.get("RELATED_INC") or "").strip() for row in related_rows if (row.get("RELATED_INC") or "").strip()})
    if not related_incs:
        return []
    lookup: dict[str, list[dict[str, str]]] = {}
    for related_inc in related_incs[:25]:
        try:
            lookup[related_inc] = run_decomp_query(
                root,
                f"select FSC,NIIN,INC,ITEM_NAME from P_FLIS_NSN WHERE INC='{related_inc}'",
            )
        except Exception:
            lookup[related_inc] = []
    return _resolve_related_nsn_candidates(compact_nsn, related_rows, lookup)


def _resolve_related_nsn_candidates(
    compact_nsn: str,
    related_rows: list[dict[str, str]],
    lookup: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    resolved: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in related_rows:
        related_inc = (row.get("RELATED_INC") or "").strip()
        source_item_name = (row.get("ITEM_NAME") or "").strip()
        if not related_inc:
            continue
        for candidate in lookup.get(related_inc, []):
            target = normalize_nsn(f"{candidate.get('FSC') or ''}{candidate.get('NIIN') or ''}")
            if not target or target.compact == compact_nsn:
                continue
            key = target.compact
            if key in seen:
                continue
            seen.add(key)
            resolved.append(
                {
                    "related_inc": related_inc,
                    "source_item_name": source_item_name,
                    "related_nsn": target.nsn,
                    "related_compact_nsn": target.compact,
                    "related_fsc": target.fsc,
                    "related_niin": target.niin,
                    "related_item_name": (candidate.get("ITEM_NAME") or "").strip() or source_item_name,
                    "relationship_type": "related_item_concept_nsn",
                }
            )
    return resolved


def _read_publog_version(root: Path) -> str | None:
    info = root / "IMD_1OF1.TXT"
    if not info.exists():
        return None
    try:
        for line in info.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Date="):
                return line.split("=", 1)[1].strip()
    except OSError:
        return None
    return None


def _upsert_master(db: Session, nsn: str, compact_nsn: str, row: dict[str, str], source_version: str | None) -> bool:
    existing = db.query(NsnMaster).filter(NsnMaster.compact_nsn == compact_nsn).first()
    if existing:
        if row.get("ITEM_NAME") and not existing.item_name:
            existing.item_name = row["ITEM_NAME"]
        if row.get("INC") and not existing.item_name_code:
            existing.item_name_code = row["INC"]
        existing.source_name = "PUB_LOG"
        existing.source_version = existing.source_version or source_version
        existing.raw_payload = existing.raw_payload or row
        db.add(existing)
        return False
    db.add(
        NsnMaster(
            nsn=nsn,
            compact_nsn=compact_nsn,
            fsc=row.get("FSC") or nsn[:4],
            niin=row.get("NIIN") or compact_nsn[4:],
            item_name=row.get("ITEM_NAME") or None,
            item_name_code=row.get("INC") or None,
            public_data_status="public",
            source_name="PUB_LOG",
            source_version=source_version,
            raw_payload=row,
        )
    )
    return True


def _upsert_reference(db: Session, nsn: str, compact_nsn: str, row: dict[str, str], source_version: str | None) -> bool:
    cage = normalize_cage(row.get("CAGE_CODE")) or None
    part_number = (row.get("PART_NUMBER") or "").strip() or None
    existing = (
        db.query(NsnReference)
        .filter(
            NsnReference.compact_nsn == compact_nsn,
            NsnReference.cage == cage,
            NsnReference.part_number == part_number,
            NsnReference.source_name == "PUB_LOG",
        )
        .first()
    )
    if existing:
        if row.get("COMPANY_NAME") and not existing.company_name:
            existing.company_name = row["COMPANY_NAME"]
        existing.source_version = existing.source_version or source_version
        existing.raw_payload = existing.raw_payload or row
        db.add(existing)
        return False
    db.add(
        NsnReference(
            nsn=nsn,
            compact_nsn=compact_nsn,
            fsc=row.get("FSC") or nsn[:4],
            niin=row.get("NIIN") or compact_nsn[4:],
            cage=cage,
            company_name=row.get("COMPANY_NAME") or None,
            part_number=part_number,
            reference_type="P_PART_PICK",
            relationship_type="manufacturer_reference",
            source_name="PUB_LOG",
            source_version=source_version,
            confidence=0.9,
            raw_payload=row,
        )
    )
    return True


def _upsert_flis_part_reference(
    db: Session,
    nsn: str,
    compact_nsn: str,
    fsc: str,
    row: dict[str, str],
    source_version: str | None,
) -> bool:
    cage = normalize_cage(row.get("CAGE_CODE")) or None
    part_number = (row.get("PART_NUMBER") or "").strip() or None
    if not cage and not part_number:
        return False
    existing = (
        db.query(NsnReference)
        .filter(
            NsnReference.compact_nsn == compact_nsn,
            NsnReference.cage == cage,
            NsnReference.part_number == part_number,
            NsnReference.source_name == "PUB_LOG_V_FLIS_PART",
        )
        .first()
    )
    payload = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "fsc": fsc,
        "niin": row.get("NIIN") or compact_nsn[4:],
        "cage": cage,
        "company_name": None,
        "part_number": part_number,
        "reference_type": row.get("RNCC") or "V_FLIS_PART",
        "relationship_type": row.get("RNVC") or "historical_reference",
        "source_name": "PUB_LOG_V_FLIS_PART",
        "source_version": source_version,
        "confidence": 0.88,
        "raw_payload": row,
    }
    if existing:
        for key, value in payload.items():
            if value and not getattr(existing, key, None):
                setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnReference(**payload))
    return True


def _upsert_cage_evidence(db: Session, nsn: str, compact_nsn: str, row: dict[str, str], source_version: str | None) -> bool:
    cage = normalize_cage(row.get("CAGE_CODE"))
    if not cage:
        return False
    existing = (
        db.query(NsnEvidence)
        .filter(
            NsnEvidence.compact_nsn == compact_nsn,
            NsnEvidence.claim_type == "cage_profile",
            NsnEvidence.claim_value == cage,
            NsnEvidence.source_name == "PUB_LOG_P_CAGE",
        )
        .first()
    )
    evidence_text = " | ".join(
        part
        for part in [
            row.get("COMPANY"),
            f"CAGE {cage}",
            row.get("CITY"),
            row.get("STATE_PROVINCE"),
            row.get("COUNTRY"),
            f"Status {row.get('CAGE_STATUS')}" if row.get("CAGE_STATUS") else None,
        ]
        if part
    )
    values = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "claim_type": "cage_profile",
        "claim_value": cage,
        "source_name": "PUB_LOG_P_CAGE",
        "source_version": source_version,
        "matched_by": "cage",
        "confidence": 0.95,
        "evidence_text": evidence_text,
        "raw_payload": row,
    }
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnEvidence(**values))
    return True


def _upsert_characteristic_evidence(
    db: Session,
    nsn: str,
    compact_nsn: str,
    row: dict[str, str],
    source_version: str | None,
) -> bool:
    mrc = (row.get("MRC") or "").strip()
    statement = (row.get("REQUIREMENTS_STATEMENT") or "").strip()
    reply = (row.get("CLEAR_TEXT_REPLY") or "").strip()
    claim_value = " | ".join(part for part in [mrc, statement] if part)[:500]
    if not claim_value and not reply:
        return False
    existing = (
        db.query(NsnEvidence)
        .filter(
            NsnEvidence.compact_nsn == compact_nsn,
            NsnEvidence.claim_type == "characteristic",
            NsnEvidence.claim_value == claim_value,
            NsnEvidence.source_name == "PUB_LOG_V_CHARACTERISTICS",
        )
        .first()
    )
    payload = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "claim_type": "characteristic",
        "claim_value": claim_value or mrc or statement,
        "source_name": "PUB_LOG_V_CHARACTERISTICS",
        "source_version": source_version,
        "matched_by": "niin",
        "confidence": 0.93,
        "evidence_text": reply or statement or mrc,
        "raw_payload": row,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnEvidence(**payload))
    return True


def _upsert_related_item_concept(
    db: Session,
    nsn: str,
    compact_nsn: str,
    row: dict[str, str],
    source_version: str | None,
) -> bool:
    related_inc = (row.get("RELATED_INC") or "").strip()
    item_name = (row.get("ITEM_NAME") or "").strip()
    if not related_inc and not item_name:
        return False
    claim_value = " | ".join(part for part in [related_inc, item_name] if part)[:500]
    existing = (
        db.query(NsnEvidence)
        .filter(
            NsnEvidence.compact_nsn == compact_nsn,
            NsnEvidence.claim_type == "related_item_concept",
            NsnEvidence.claim_value == claim_value,
            NsnEvidence.source_name == "PUB_LOG_V_H6_RELATED",
        )
        .first()
    )
    payload = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "claim_type": "related_item_concept",
        "claim_value": claim_value,
        "source_name": "PUB_LOG_V_H6_RELATED",
        "source_version": source_version,
        "matched_by": "inc",
        "confidence": 0.8,
        "evidence_text": f"Related INC {related_inc} for {item_name}".strip(),
        "raw_payload": row,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnEvidence(**payload))
    return True


def _upsert_related_interchange(
    db: Session,
    nsn: str,
    compact_nsn: str,
    row: dict[str, str],
    source_version: str | None,
) -> bool:
    related_inc = (row.get("RELATED_INC") or "").strip()
    if not related_inc:
        return False
    related_nsn = f"INC-{related_inc}"
    existing = (
        db.query(NsnInterchangeability)
        .filter(
            NsnInterchangeability.compact_nsn == compact_nsn,
            NsnInterchangeability.related_compact_nsn == related_inc,
            NsnInterchangeability.relationship_type == "related_item_concept",
            NsnInterchangeability.source_name == "PUB_LOG_V_H6_RELATED",
        )
        .first()
    )
    payload = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "related_nsn": related_nsn,
        "related_compact_nsn": related_inc,
        "relationship_type": "related_item_concept",
        "order_of_use": None,
        "source_name": "PUB_LOG_V_H6_RELATED",
        "source_version": source_version,
        "confidence": 0.6,
        "notes": row.get("ITEM_NAME"),
        "raw_payload": row,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnInterchangeability(**payload))
    return True


def _upsert_related_nsn_evidence(
    db: Session,
    nsn: str,
    compact_nsn: str,
    row: dict[str, str],
    source_version: str | None,
) -> bool:
    related_nsn = (row.get("related_nsn") or "").strip()
    if not related_nsn:
        return False
    claim_value = " | ".join(
        part
        for part in [related_nsn, row.get("related_item_name"), f"INC {row.get('related_inc')}" if row.get("related_inc") else None]
        if part
    )[:500]
    existing = (
        db.query(NsnEvidence)
        .filter(
            NsnEvidence.compact_nsn == compact_nsn,
            NsnEvidence.claim_type == "related_nsn_candidate",
            NsnEvidence.claim_value == claim_value,
            NsnEvidence.source_name == "PUB_LOG_V_H6_RELATED",
        )
        .first()
    )
    payload = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "claim_type": "related_nsn_candidate",
        "claim_value": claim_value,
        "source_name": "PUB_LOG_V_H6_RELATED",
        "source_version": source_version,
        "matched_by": "related_inc_to_nsn",
        "confidence": 0.74,
        "evidence_text": f"Resolved related INC {row.get('related_inc')} to NSN {related_nsn}",
        "raw_payload": row,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnEvidence(**payload))
    return True


def _upsert_resolved_related_interchange(
    db: Session,
    nsn: str,
    compact_nsn: str,
    row: dict[str, str],
    source_version: str | None,
) -> bool:
    related_nsn = (row.get("related_nsn") or "").strip()
    related_compact_nsn = (row.get("related_compact_nsn") or "").strip()
    if not related_nsn or not related_compact_nsn:
        return False
    existing = (
        db.query(NsnInterchangeability)
        .filter(
            NsnInterchangeability.compact_nsn == compact_nsn,
            NsnInterchangeability.related_compact_nsn == related_compact_nsn,
            NsnInterchangeability.relationship_type == "related_item_concept_nsn",
            NsnInterchangeability.source_name == "PUB_LOG_V_H6_RELATED",
        )
        .first()
    )
    payload = {
        "nsn": nsn,
        "compact_nsn": compact_nsn,
        "related_nsn": related_nsn,
        "related_compact_nsn": related_compact_nsn,
        "relationship_type": "related_item_concept_nsn",
        "order_of_use": None,
        "source_name": "PUB_LOG_V_H6_RELATED",
        "source_version": source_version,
        "confidence": 0.72 if row.get("related_fsc") == nsn[:4] else 0.68,
        "notes": row.get("related_item_name") or row.get("source_item_name"),
        "raw_payload": row,
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        db.add(existing)
        return False
    db.add(NsnInterchangeability(**payload))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Import one NSN from a PUB LOG Decomp working folder.")
    parser.add_argument("nsn")
    parser.add_argument("--publog-dir", default=str(DEFAULT_PUBLOG_DIR))
    parser.add_argument("--source-version", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = import_publog_nsn(
            db,
            args.nsn,
            publog_dir=args.publog_dir,
            source_version=args.source_version,
            dry_run=args.dry_run,
        )
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
