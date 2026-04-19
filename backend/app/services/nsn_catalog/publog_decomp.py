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
from app.models.nsn_catalog import NsnMaster, NsnReference
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
        if completed.returncode != 0 and not rows:
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

    master_created = False
    references_created = 0
    references_updated = 0
    if not dry_run:
        if nsn_rows:
            master_created = _upsert_master(db, target.nsn, target.compact, nsn_rows[0], source_version)
        for row in part_rows:
            created = _upsert_reference(db, target.nsn, target.compact, row, source_version)
            references_created += int(created)
            references_updated += int(not created)
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
        "master_created": master_created,
        "references_created": references_created,
        "references_updated": references_updated,
        "identity_sample": nsn_rows[:1],
        "part_samples": part_rows[:10],
    }


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
