from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnReference
from app.models.opportunity import Opportunity
from app.models.provider import Provider, ProviderItem
from app.models.vendor import VendorLead, VendorQuote
from app.services.app_settings_service import get_setting, upsert_setting
from app.services.org_service import ensure_default_organization
from app.services.storage import ensure_dir, storage_root

DEFAULT_FILENAME = "nagacon_master_catalog.csv"


def get_master_catalog_export_path(db: Session, organization_id: int | None = None) -> str:
    org_id = organization_id
    if org_id is None:
        org = ensure_default_organization(db)
        org_id = getattr(org, "id", None)
    return (get_setting(db, "master_catalog_export_path", default="", organization_id=org_id) or "").strip()


def resolve_master_catalog_export_path(db: Session, organization_id: int | None = None) -> Path | None:
    configured = get_master_catalog_export_path(db, organization_id=organization_id)
    if not configured:
        return None
    path = Path(configured)
    if path.suffix:
        return path
    return path / DEFAULT_FILENAME


def build_master_catalog_rows(db: Session, organization_id: int | None = None) -> list[dict[str, str]]:
    cage_name_map = _build_cage_name_map(db, organization_id=organization_id)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add_row(*, fsc: str | None, nsn: str | None, vendor: str | None, part_number: str | None) -> None:
        clean_fsc = _clean(fsc)
        clean_nsn = _clean(nsn)
        clean_vendor = _clean(vendor)
        clean_part = _clean(part_number)
        key = (
            (clean_fsc or "").upper(),
            (clean_nsn or "").upper(),
            (clean_vendor or "").upper(),
            (clean_part or "").upper(),
        )
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "fsc": clean_fsc or "",
                "nsn": clean_nsn or "",
                "vendor": clean_vendor or "",
                "part_number": clean_part or "",
            }
        )

    reference_query = db.query(NsnReference)
    for row in reference_query.all():
        vendor_name = _enriched_vendor_name(cage_name_map, cage=row.cage, vendor=row.company_name)
        add_row(fsc=row.fsc, nsn=row.nsn, vendor=vendor_name, part_number=row.part_number)

    provider_items_query = db.query(ProviderItem, Provider).join(Provider, Provider.id == ProviderItem.provider_id)
    if organization_id is not None:
        provider_items_query = provider_items_query.filter(
            or_(Provider.organization_id == organization_id, Provider.organization_id.is_(None))
        )
    for item, provider in provider_items_query.all():
        vendor_name = _enriched_vendor_name(
            cage_name_map,
            cage=getattr(provider, "cage", None),
            vendor=getattr(provider, "canonical_name", None) or getattr(provider, "company_name", None),
        )
        add_row(fsc=item.fsc, nsn=item.nsn, vendor=vendor_name, part_number=None)

    vendor_lead_query = db.query(VendorLead, Opportunity).join(Opportunity, Opportunity.id == VendorLead.opportunity_id)
    if organization_id is not None:
        vendor_lead_query = vendor_lead_query.filter(
            or_(VendorLead.organization_id == organization_id, VendorLead.organization_id.is_(None))
        )
    for lead, opp in vendor_lead_query.all():
        vendor_name = _enriched_vendor_name(cage_name_map, cage=lead.cage, vendor=lead.company_name)
        add_row(fsc=getattr(opp, "fsc", None), nsn=lead.nsn, vendor=vendor_name, part_number=lead.part_number)

    vendor_quote_query = db.query(VendorQuote, Opportunity).join(Opportunity, Opportunity.id == VendorQuote.opportunity_id)
    if organization_id is not None:
        vendor_quote_query = vendor_quote_query.filter(
            or_(VendorQuote.organization_id == organization_id, VendorQuote.organization_id.is_(None))
        )
    for quote, opp in vendor_quote_query.all():
        vendor_name = _enriched_vendor_name(cage_name_map, cage=quote.cage, vendor=quote.company_name)
        add_row(fsc=getattr(opp, "fsc", None), nsn=None, vendor=vendor_name, part_number=quote.part_number)

    return sorted(rows, key=lambda row: (row["fsc"], row["nsn"], row["vendor"], row["part_number"]))


def write_master_catalog_export(db: Session, organization_id: int | None = None) -> dict[str, str | int | bool | None]:
    target = resolve_master_catalog_export_path(db, organization_id=organization_id)
    if target is None:
        return {"written": False, "reason": "path_not_configured", "path": None, "row_count": 0}

    rows = build_master_catalog_rows(db, organization_id=organization_id)
    ensure_dir(target.parent)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["fsc", "nsn", "vendor", "part_number"])
        writer.writeheader()
        writer.writerows(rows)

    org_id = organization_id
    if org_id is None:
        org = ensure_default_organization(db)
        org_id = getattr(org, "id", None)
    upsert_setting(db, "master_catalog_export_last_written_at", datetime.utcnow().isoformat(), organization_id=org_id)
    upsert_setting(db, "master_catalog_export_last_row_count", str(len(rows)), organization_id=org_id)

    return {
        "written": True,
        "path": str(target),
        "row_count": len(rows),
    }


def _build_cage_name_map(db: Session, organization_id: int | None = None) -> dict[str, str]:
    query = db.query(Provider)
    if organization_id is not None:
        query = query.filter(or_(Provider.organization_id == organization_id, Provider.organization_id.is_(None)))
    rows = query.all()
    mapping: dict[str, str] = {}
    for provider in rows:
        cage = _clean(getattr(provider, "cage", None))
        if not cage:
            continue
        name = _clean(getattr(provider, "canonical_name", None)) or _clean(getattr(provider, "company_name", None))
        if not name:
            continue
        current = mapping.get(cage.upper())
        if not current or current.upper().startswith("CAGE "):
            mapping[cage.upper()] = name
    return mapping


def _enriched_vendor_name(cage_name_map: dict[str, str], *, cage: str | None, vendor: str | None) -> str | None:
    clean_cage = _clean(cage)
    if clean_cage:
        enriched = cage_name_map.get(clean_cage.upper())
        if enriched:
            return enriched
    return _clean(vendor) or (f"CAGE {clean_cage}" if clean_cage else None)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None
