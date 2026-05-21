from __future__ import annotations

from pathlib import Path

from app.services import master_catalog_export


class FakeDB:
    pass


def test_write_master_catalog_export_persists_success(tmp_path, monkeypatch):
    target = tmp_path / "nagacon_master_catalog.csv"
    statuses: list[dict[str, object]] = []

    monkeypatch.setattr(master_catalog_export, "resolve_master_catalog_export_path", lambda db, organization_id=None: target)
    monkeypatch.setattr(
        master_catalog_export,
        "build_master_catalog_rows",
        lambda db, organization_id=None: [{"fsc": "5306", "nsn": "5306000039356", "vendor": "Acme", "part_number": "NAS630-35"}],
    )
    monkeypatch.setattr(master_catalog_export, "ensure_default_organization", lambda db: type("Org", (), {"id": 1})())
    monkeypatch.setattr(
        master_catalog_export,
        "_persist_export_status",
        lambda db, organization_id=None, result=None: statuses.append(dict(result or {})),
    )

    result = master_catalog_export.write_master_catalog_export(FakeDB(), organization_id=1)

    assert result["written"] is True
    assert result["status"] == "OK"
    assert target.exists()
    assert statuses[-1]["status"] == "OK"


def test_write_master_catalog_export_handles_permission_failure(tmp_path, monkeypatch):
    target = tmp_path / "nagacon_master_catalog.csv"
    statuses: list[dict[str, object]] = []

    monkeypatch.setattr(master_catalog_export, "resolve_master_catalog_export_path", lambda db, organization_id=None: target)
    monkeypatch.setattr(
        master_catalog_export,
        "build_master_catalog_rows",
        lambda db, organization_id=None: [{"fsc": "5306", "nsn": "5306000039356", "vendor": "Acme", "part_number": "NAS630-35"}],
    )
    monkeypatch.setattr(master_catalog_export, "ensure_default_organization", lambda db: type("Org", (), {"id": 1})())
    monkeypatch.setattr(
        master_catalog_export,
        "_persist_export_status",
        lambda db, organization_id=None, result=None: statuses.append(dict(result or {})),
    )
    monkeypatch.setattr(
        master_catalog_export,
        "_write_master_catalog_csv",
        lambda target, rows: (_ for _ in ()).throw(PermissionError("Access is denied")),
    )

    result = master_catalog_export.write_master_catalog_export(FakeDB(), organization_id=1)

    assert result["written"] is False
    assert result["status"] == "FAILED"
    assert result["reason"] == "write_failed"
    assert "Access is denied" in str(result["error"])
    assert statuses[-1]["status"] == "FAILED"


def test_write_master_catalog_csv_replaces_existing_file(tmp_path):
    target = tmp_path / "nagacon_master_catalog.csv"
    target.write_text("old,data\n", encoding="utf-8")

    master_catalog_export._write_master_catalog_csv(
        target,
        [{"fsc": "5306", "nsn": "5306000039356", "vendor": "Acme", "part_number": "NAS630-35"}],
    )

    contents = target.read_text(encoding="utf-8")
    assert "old,data" not in contents
    assert "Acme" in contents
