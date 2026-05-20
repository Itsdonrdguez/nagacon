from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.services import closed_solicitation_processing as processing

TEST_TEMP_DIR = Path(__file__).resolve().parent / "_tmp"


class FakeDB:
    def __init__(self) -> None:
        self.audit_records: list[SimpleNamespace] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.next_id = 1

    def add(self, item):
        if isinstance(item, SimpleNamespace) and getattr(item, "_audit_record", False):
            if getattr(item, "id", None) is None:
                item.id = self.next_id
                self.next_id += 1
                self.audit_records.append(item)
        return None

    def flush(self):
        return None

    def commit(self):
        self.commit_count += 1

    def refresh(self, item):
        return None

    def rollback(self):
        self.rollback_count += 1


def _make_temp_file(name: str = "sample.pdf", content: bytes = b"%PDF-1.4 sample") -> Path:
    TEST_TEMP_DIR.mkdir(exist_ok=True)
    path = TEST_TEMP_DIR / name
    path.write_bytes(content)
    return path


def _file_record(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        organization_id=1,
        opportunity_id=77,
        filename=path.name,
        file_path=str(path),
        source_url="https://drive.test/sample.pdf",
        extracted_text="parsed text",
        parsed_metadata={"_retention": {"downstream_complete": True}},
        created_at=datetime.utcnow() - timedelta(days=1),
    )


def _opportunity() -> SimpleNamespace:
    return SimpleNamespace(
        id=77,
        organization_id=1,
        solicitation_number="SPE2DH26Q0073",
        due_at=datetime.utcnow() - timedelta(days=10),
        parsed_json={"nsn": "6520-00-721-9355"},
    )


def _install_fake_audit_store(monkeypatch):
    def fake_find(db, *, record_id, opportunity_id, file_sha256):
        for record in db.audit_records:
            if record_id and getattr(record, "id", None) == record_id:
                return record
            if opportunity_id is not None and file_sha256 and record.opportunity_id == opportunity_id and record.file_sha256 == file_sha256:
                return record
        return None

    def fake_upsert(
        db,
        *,
        file_record,
        opportunity,
        snapshot,
        status,
        error_message,
        processed_at,
        deletion_timestamp,
        existing,
    ):
        record = existing or fake_find(
            db,
            record_id=None,
            opportunity_id=getattr(file_record, "opportunity_id", None),
            file_sha256=snapshot["file_sha256"],
        )
        if record is None:
            record = SimpleNamespace(_audit_record=True)
        record.organization_id = getattr(file_record, "organization_id", None)
        record.opportunity_id = getattr(file_record, "opportunity_id", None)
        record.opportunity_file_id = getattr(file_record, "id", None)
        record.solicitation_number = snapshot.get("solicitation_number")
        record.nsn = snapshot.get("nsn")
        record.part_numbers = list(snapshot.get("part_numbers") or [])
        record.vendor_names = list(snapshot.get("vendor_names") or [])
        record.cage_codes = list(snapshot.get("cage_codes") or [])
        record.pricing_history_notes = snapshot.get("pricing_history_notes")
        record.original_source_file_name = snapshot.get("original_source_file_name")
        record.original_source_url = snapshot.get("original_source_url")
        record.local_path_before_deletion = snapshot.get("local_path_before_deletion")
        record.file_size_bytes = snapshot.get("file_size_bytes")
        record.file_sha256 = snapshot["file_sha256"]
        record.extraction_status = status
        record.processed_at = processed_at
        record.deletion_timestamp = deletion_timestamp
        record.error_message = error_message
        record.last_seen_at = snapshot.get("last_seen_at")
        record.last_processed_at = snapshot.get("last_processed_at")
        record.source_updated_at = snapshot.get("source_updated_at")
        db.add(record)
        return record

    monkeypatch.setattr(processing, "_find_processing_record", fake_find)
    monkeypatch.setattr(processing, "_upsert_processing_record", fake_upsert)


def test_successful_closed_file_processing_audits_then_deletes(monkeypatch):
    db = FakeDB()
    file_path = _make_temp_file()
    file_record = _file_record(file_path)
    opportunity = _opportunity()
    _install_fake_audit_store(monkeypatch)

    def fake_snapshot(db, *, file_record, opportunity, source_url, fingerprint, processed_at):
        return {
            "solicitation_number": opportunity.solicitation_number,
            "nsn": "6520-00-721-9355",
            "part_numbers": ["123-ABC"],
            "vendor_names": ["ACME DENTAL"],
            "cage_codes": ["1ABC2"],
            "pricing_history_notes": "unit 19.50 | source prior award",
            "original_source_file_name": file_record.filename,
            "original_source_url": source_url,
            "local_path_before_deletion": file_record.file_path,
            "file_size_bytes": fingerprint["file_size_bytes"],
            "file_sha256": fingerprint["file_sha256"],
            "source_updated_at": fingerprint["source_updated_at"],
            "processed_at": processed_at,
            "last_seen_at": processed_at,
            "last_processed_at": processed_at,
        }

    monkeypatch.setattr(processing, "_build_closed_solicitation_snapshot", fake_snapshot)

    result = processing.process_closed_solicitation_file(db, file_record, opportunity=opportunity)

    assert result["extraction_status"] == processing.STATUS_PROCESSED_DELETED
    assert result["deleted"] is True
    assert not file_path.exists()
    assert str(file_record.file_path).startswith("pruned://opportunity-file/")
    assert len(db.audit_records) == 1
    assert db.audit_records[0].extraction_status == processing.STATUS_PROCESSED_DELETED
    assert db.audit_records[0].deletion_timestamp is not None
    closed_meta = file_record.parsed_metadata["_retention"]["closed_processing"]
    assert closed_meta["audit_record_id"] == db.audit_records[0].id


def test_extraction_failure_keeps_file_and_marks_failed(monkeypatch):
    db = FakeDB()
    file_path = _make_temp_file("failure.pdf")
    file_record = _file_record(file_path)
    opportunity = _opportunity()
    _install_fake_audit_store(monkeypatch)

    def fail_snapshot(*args, **kwargs):
        raise ValueError("parse failed")

    monkeypatch.setattr(processing, "_build_closed_solicitation_snapshot", fail_snapshot)

    result = processing.process_closed_solicitation_file(db, file_record, opportunity=opportunity)

    assert result["status"] == "extraction_failed"
    assert result["extraction_status"] == processing.STATUS_PROCESSED_FAILED
    assert file_path.exists()
    assert len(db.audit_records) == 1
    assert db.audit_records[0].extraction_status == processing.STATUS_PROCESSED_FAILED
    assert "parse failed" in (db.audit_records[0].error_message or "")


def test_audit_persistence_failure_keeps_file(monkeypatch):
    db = FakeDB()
    file_path = _make_temp_file("audit-fail.pdf")
    file_record = _file_record(file_path)
    opportunity = _opportunity()
    monkeypatch.setattr(processing, "_find_processing_record", lambda *args, **kwargs: None)

    def fail_upsert(*args, **kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(processing, "_upsert_processing_record", fail_upsert)

    delete_called = {"value": False}

    def fail_if_delete(reference):
        delete_called["value"] = True
        return False

    monkeypatch.setattr(processing, "delete_reference", fail_if_delete)

    result = processing.process_closed_solicitation_file(db, file_record, opportunity=opportunity)

    assert result["status"] == "audit_persist_failed"
    assert result["deleted"] is False
    assert file_path.exists()
    assert delete_called["value"] is False


def test_rerun_does_not_duplicate_audit_rows(monkeypatch):
    db = FakeDB()
    file_path = _make_temp_file("rerun.pdf")
    file_record = _file_record(file_path)
    opportunity = _opportunity()
    _install_fake_audit_store(monkeypatch)

    def fake_snapshot(db, *, file_record, opportunity, source_url, fingerprint, processed_at):
        return {
            "solicitation_number": opportunity.solicitation_number,
            "nsn": "6520-00-721-9355",
            "part_numbers": ["123-ABC"],
            "vendor_names": ["ACME DENTAL"],
            "cage_codes": ["1ABC2"],
            "pricing_history_notes": None,
            "original_source_file_name": file_record.filename,
            "original_source_url": source_url,
            "local_path_before_deletion": file_record.file_path,
            "file_size_bytes": fingerprint["file_size_bytes"],
            "file_sha256": fingerprint["file_sha256"],
            "source_updated_at": fingerprint["source_updated_at"],
            "processed_at": processed_at,
            "last_seen_at": processed_at,
            "last_processed_at": processed_at,
        }

    monkeypatch.setattr(processing, "_build_closed_solicitation_snapshot", fake_snapshot)

    first = processing.process_closed_solicitation_file(db, file_record, opportunity=opportunity)
    second = processing.process_closed_solicitation_file(db, file_record, opportunity=opportunity)

    assert first["extraction_status"] == processing.STATUS_PROCESSED_DELETED
    assert second["status"] == "already_processed"
    assert len(db.audit_records) == 1
    assert second["audit_record_id"] == db.audit_records[0].id


def test_storage_cleanup_dir_uses_configured_pdf_root(monkeypatch):
    db = FakeDB()
    pdf_root = TEST_TEMP_DIR / "pdf-root"
    file_path = pdf_root / "SPE2DH26Q0073" / "documents" / "sample.pdf"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"%PDF-1.4 sample")

    monkeypatch.setattr(processing, "storage_root", lambda base_dir=None: TEST_TEMP_DIR / "other-root")
    monkeypatch.setattr(processing, "effective_pdf_download_root", lambda db, organization_id=None: pdf_root)
    monkeypatch.setattr(processing, "get_setting", lambda db, key, default="", organization_id=None: str(pdf_root) if key == "pdf_download_path" else default)

    cleanup_dir = processing._storage_cleanup_dir_for_reference(db, str(file_path), organization_id=1)

    assert cleanup_dir == str(file_path.parent.parent.resolve())


def test_storage_cleanup_dir_allows_existing_absolute_path_outside_default_root(monkeypatch):
    db = FakeDB()
    file_path = TEST_TEMP_DIR / "custom-absolute" / "SPE2DH26Q0073" / "documents" / "sample.pdf"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"%PDF-1.4 sample")

    monkeypatch.setattr(processing, "storage_root", lambda base_dir=None: TEST_TEMP_DIR / "other-root")
    monkeypatch.setattr(processing, "effective_pdf_download_root", lambda db, organization_id=None: TEST_TEMP_DIR / "other-root")
    monkeypatch.setattr(processing, "get_setting", lambda db, key, default="", organization_id=None: "")

    cleanup_dir = processing._storage_cleanup_dir_for_reference(db, str(file_path), organization_id=1)

    assert cleanup_dir == str(file_path.parent.parent.resolve())


def test_file_ready_accepts_derived_downstream_completion(monkeypatch):
    from app.services import file_retention

    monkeypatch.setattr(file_retention, "_downstream_processing_complete", lambda file_record, opportunity=None: True)
    file_record = SimpleNamespace(
        file_path=str(TEST_TEMP_DIR / "derived-ready.pdf"),
        extracted_text="parsed text",
        parsed_metadata={
            "_retention": {"downstream_complete": False},
            "_pipeline": {"status": "completed", "review_required": False},
        },
        opportunity=SimpleNamespace(id=77),
    )

    assert processing._file_ready_for_closed_processing(file_record) is True


def test_remove_storage_dirs_prunes_disposable_residue():
    solicitation_dir = TEST_TEMP_DIR / "residue-only" / "documents"
    solicitation_dir.mkdir(parents=True, exist_ok=True)
    (solicitation_dir.parent / "desktop.ini").write_text("", encoding="utf-8")
    (solicitation_dir / "desktop.ini").write_text("", encoding="utf-8")
    (solicitation_dir / "sample_official_pdf_debug.json").write_text("{}", encoding="utf-8")

    removed = processing._remove_storage_dirs({str(solicitation_dir.parent)})

    assert removed is True
    assert not solicitation_dir.parent.exists()


def test_prune_disposable_residue_removes_empty_nested_tree():
    solicitation_dir = TEST_TEMP_DIR / "empty-only" / "documents"
    solicitation_dir.mkdir(parents=True, exist_ok=True)

    processing._prune_disposable_residue(solicitation_dir.parent)

    assert not solicitation_dir.parent.exists()


def test_prune_disposable_residue_removes_readonly_empty_tree():
    solicitation_dir = TEST_TEMP_DIR / "readonly-empty" / "documents"
    solicitation_dir.mkdir(parents=True, exist_ok=True)
    solicitation_dir.chmod(0o777)
    solicitation_dir.parent.chmod(0o777)

    processing._prune_disposable_residue(solicitation_dir.parent)

    assert not solicitation_dir.parent.exists()
