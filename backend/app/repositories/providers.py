from __future__ import annotations

import csv
import io
import re
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.provider import Provider, ProviderItem
from app.models.vendor import VendorLead
from app.models.award_history import AwardHistory
from app.models.nsn_catalog import NsnReference, NsnAwardEvidence
from app.schemas.provider import ProviderCreate, ProviderImportResult, ProviderItemCreate, ProviderUpdate
from app.services.org_service import ensure_default_organization
from app.services.providers.identity_resolver import resolve_provider_identity


def _clean(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return None
    return text[:max_len] if max_len else text


def _normalize_cage(value: str | None) -> str | None:
    value = _clean(value, 20)
    return value.upper() if value else None


def _normalize_nsn(value: str | None) -> str | None:
    value = _clean(value, 40)
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 13:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
    return value.upper()


def _derive_fsc(nsn: str | None, fsc: str | None) -> str | None:
    explicit = re.sub(r"\D", "", str(fsc or ""))
    if len(explicit) >= 4:
        return explicit[:4]
    nsn_digits = re.sub(r"\D", "", str(nsn or ""))
    if len(nsn_digits) >= 4:
        return nsn_digits[:4]
    return None


def _display_source(value: str | None) -> str:
    text = (_clean(value, 100) or "Workspace Vendor Lead").replace("_", " ").strip()
    if text.upper() == "DIBBS APPROVED SOURCE":
        return "DIBBS Approved Source"
    if text.upper() == "USASPENDING":
        return "USAspending"
    return text.title()


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value == "":
            continue
        key = str(value).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


class ProviderRepository:
    def __init__(self, db: Session, organization_id: int | None = None):
        self.db = db
        self.organization_id = organization_id

    def _org_id(self) -> int | None:
        if self.organization_id is not None:
            return self.organization_id
        org = ensure_default_organization(self.db)
        return getattr(org, "id", None)

    def _scoped_query(self):
        query = self.db.query(Provider)
        org_id = self._org_id()
        if org_id is not None:
            query = query.filter(Provider.organization_id == org_id)
        return query

    def _find_provider(self, *, company_name: str | None, cage: str | None, uei: str | None) -> Provider | None:
        query = self._scoped_query()
        cage = _normalize_cage(cage)
        uei = _clean(uei, 40)
        if cage:
            found = query.filter(func.upper(Provider.cage) == cage).first()
            if found:
                return found
        if uei:
            found = query.filter(func.upper(Provider.uei) == uei.upper()).first()
            if found:
                return found
        name = _clean(company_name, 240)
        if name:
            found = query.filter(func.lower(Provider.company_name) == name.lower()).first()
            if found:
                return found
        return None

    def _add_item(self, provider: Provider, item: ProviderItemCreate | None) -> ProviderItem | None:
        if not item:
            return None
        nsn = _normalize_nsn(item.nsn)
        fsc = _derive_fsc(nsn, item.fsc)
        relationship_type = _clean(item.relationship_type, 60) or "Unknown"
        source = _clean(item.source, 100) or "Manual"

        existing = (
            self.db.query(ProviderItem)
            .filter(
                ProviderItem.provider_id == provider.id,
                ProviderItem.nsn == nsn,
                ProviderItem.relationship_type == relationship_type,
                ProviderItem.source == source,
            )
            .first()
        )
        if existing:
            if item.nomenclature and not existing.nomenclature:
                existing.nomenclature = _clean(item.nomenclature, 300)
            if item.source_url and not existing.source_url:
                existing.source_url = _clean(item.source_url, 700)
            if item.notes and not existing.notes:
                existing.notes = _clean(item.notes)
            self.db.add(existing)
            return existing

        rec = ProviderItem(
            provider_id=provider.id,
            nsn=nsn,
            fsc=fsc,
            nomenclature=_clean(item.nomenclature, 300),
            relationship_type=relationship_type,
            source=source,
            source_url=_clean(item.source_url, 700),
            confidence=item.confidence,
            notes=_clean(item.notes),
        )
        self.db.add(rec)
        return rec

    def create(self, payload: ProviderCreate) -> Provider:
        provider = self._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
        if provider is None:
            provider = Provider(
                organization_id=self._org_id(),
                company_name=_clean(payload.company_name, 240) or "Unknown Provider",
                cage=_normalize_cage(payload.cage),
                uei=_clean(payload.uei, 40),
                website=_clean(payload.website, 500),
                contact_name=_clean(payload.contact_name, 160),
                email=_clean(payload.email, 240),
                phone=_clean(payload.phone, 80),
                notes=_clean(payload.notes),
                status=_clean(payload.status, 40) or "active",
            )
            self.db.add(provider)
            self.db.flush()
        else:
            incoming_name = _clean(payload.company_name, 240)
            placeholder_names = {
                "UNKNOWN PROVIDER",
                f"CAGE {provider.cage}".upper() if provider.cage else "",
            }
            contaminated_name = bool(
                incoming_name
                and len(provider.company_name or "") > 120
                and len(incoming_name) < 100
            )
            if incoming_name and (provider.company_name.upper() in placeholder_names or contaminated_name):
                provider.company_name = incoming_name
            for field in ["website", "contact_name", "email", "phone", "notes"]:
                incoming = _clean(getattr(payload, field, None), 500 if field == "website" else None)
                if incoming and not getattr(provider, field):
                    setattr(provider, field, incoming)
            if payload.cage and not provider.cage:
                provider.cage = _normalize_cage(payload.cage)
            if payload.uei and not provider.uei:
                provider.uei = _clean(payload.uei, 40)
            self.db.add(provider)

        self._add_item(provider, payload.item)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            provider = self._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
            if provider is None:
                raise
            self._add_item(provider, payload.item)
            self.db.commit()
        self.db.refresh(provider)
        resolve_provider_identity(self.db, provider)
        self.db.commit()
        self.db.refresh(provider)
        return provider

    def update(self, provider_id: int, payload: ProviderUpdate) -> Provider | None:
        provider = self._scoped_query().filter(Provider.id == provider_id).first()
        if not provider:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            if key == "cage":
                value = _normalize_cage(value)
            elif key == "company_name":
                value = _clean(value, 240) or provider.company_name
            elif key == "website":
                value = _clean(value, 500)
            else:
                value = _clean(value)
            setattr(provider, key, value)
        self.db.commit()
        self.db.refresh(provider)
        return provider

    def get_detail(self, provider_id: int) -> dict[str, Any] | None:
        provider = (
            self._scoped_query()
            .options(selectinload(Provider.items))
            .filter(Provider.id == provider_id)
            .first()
        )
        if not provider:
            return None

        items = sorted(provider.items or [], key=lambda item: (item.nsn or "", item.relationship_type or "", item.source or ""))
        nsns = [item.nsn for item in items if item.nsn]
        cage = _normalize_cage(provider.cage)
        company = _clean(provider.company_name, 240)

        award_query = self.db.query(AwardHistory)
        if cage or company:
            filters = []
            if cage:
                filters.append(func.upper(AwardHistory.recipient_cage) == cage)
            if company:
                filters.append(func.lower(AwardHistory.recipient_name) == company.lower())
            award_query = award_query.filter(or_(*filters))
        else:
            award_query = award_query.filter(AwardHistory.id == -1)
        awards = award_query.order_by(AwardHistory.award_date.desc().nullslast()).limit(50).all()

        nsn_award_query = self.db.query(NsnAwardEvidence)
        if cage or company:
            filters = []
            if cage:
                filters.append(func.upper(NsnAwardEvidence.recipient_cage) == cage)
            if company:
                filters.append(func.lower(NsnAwardEvidence.recipient_name) == company.lower())
            nsn_award_query = nsn_award_query.filter(or_(*filters))
        else:
            nsn_award_query = nsn_award_query.filter(NsnAwardEvidence.id == -1)
        nsn_awards = nsn_award_query.order_by(NsnAwardEvidence.award_date.desc().nullslast()).limit(50).all()

        reference_query = self.db.query(NsnReference)
        if nsns:
            reference_query = reference_query.filter(NsnReference.nsn.in_(nsns))
        if cage:
            reference_query = reference_query.filter(NsnReference.cage == cage)
        references = reference_query.order_by(NsnReference.updated_at.desc()).limit(100).all()

        return {
            "provider": {
                "id": provider.id,
                "company_name": provider.company_name,
                "canonical_name": provider.canonical_name,
                "cage": provider.cage,
                "uei": provider.uei,
                "website": provider.website,
                "contact_name": provider.contact_name,
                "email": provider.email,
                "phone": provider.phone,
                "notes": provider.notes,
                "status": provider.status,
                "identity_source": provider.identity_source,
                "identity_confidence": provider.identity_confidence,
                "aliases": provider.aliases or [],
                "created_at": provider.created_at.isoformat() if provider.created_at else None,
                "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
            },
            "items": [
                {
                    "provider_item_id": item.id,
                    "nsn": item.nsn,
                    "fsc": item.fsc,
                    "nomenclature": item.nomenclature,
                    "relationship_type": item.relationship_type,
                    "source": item.source,
                    "source_url": item.source_url,
                    "confidence": item.confidence,
                    "notes": item.notes,
                }
                for item in items
            ],
            "award_history": [
                {
                    "source_system": row.source_system,
                    "award_id": row.award_id,
                    "piid": row.piid,
                    "nsn": row.nsn,
                    "award_date": row.award_date,
                    "award_amount": row.award_amount,
                    "awarding_agency": row.awarding_agency,
                    "description": row.description,
                    "match_confidence": row.match_confidence,
                }
                for row in awards
            ],
            "nsn_award_evidence": [
                {
                    "source_system": row.source_system,
                    "award_id": row.award_id,
                    "piid": row.piid,
                    "nsn": row.nsn,
                    "award_date": row.award_date,
                    "award_amount": row.award_amount,
                    "awarding_agency": row.awarding_agency,
                    "description": row.description,
                    "match_confidence": row.match_confidence,
                    "match_reasons": row.match_reasons,
                }
                for row in nsn_awards
            ],
            "catalog_references": [
                {
                    "nsn": row.nsn,
                    "part_number": row.part_number,
                    "reference_type": row.reference_type,
                    "relationship_type": row.relationship_type,
                    "source_name": row.source_name,
                    "source_version": row.source_version,
                    "confidence": row.confidence,
                }
                for row in references
            ],
            "summary": {
                "item_count": len(items),
                "award_history_count": len(awards),
                "nsn_award_evidence_count": len(nsn_awards),
                "catalog_reference_count": len(references),
                "nsn_count": len(_unique(nsns)),
            },
        }

    def list_rows(
        self,
        *,
        q: str | None = None,
        nsn: str | None = None,
        fsc: str | None = None,
        relationship_type: str | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        org_id = self._org_id()
        query = self.db.query(Provider.id).outerjoin(ProviderItem, ProviderItem.provider_id == Provider.id)
        if org_id is not None:
            query = query.filter(Provider.organization_id == org_id)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    Provider.company_name.ilike(pattern),
                    Provider.cage.ilike(pattern),
                    Provider.uei.ilike(pattern),
                    ProviderItem.nomenclature.ilike(pattern),
                    ProviderItem.nsn.ilike(pattern),
                )
            )
        if nsn:
            normalized = re.sub(r"\D", "", nsn)
            if normalized:
                compact_nsn = func.replace(func.replace(func.replace(ProviderItem.nsn, "-", ""), " ", ""), ".", "")
                query = query.filter(compact_nsn.ilike(f"%{normalized}%"))
        if fsc:
            query = query.filter(ProviderItem.fsc == _derive_fsc(None, fsc))
        if relationship_type and relationship_type != "all":
            query = query.filter(ProviderItem.relationship_type == relationship_type)
        if source and source != "all":
            query = query.filter(ProviderItem.source == source)

        distinct_ids = query.distinct()
        total = distinct_ids.count()
        page_ids = [
            row[0]
            for row in distinct_ids
            .order_by(Provider.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        ]
        if not page_ids:
            return [], total

        providers = (
            self.db.query(Provider)
            .options(selectinload(Provider.items))
            .filter(Provider.id.in_(page_ids))
            .all()
        )
        provider_by_id = {provider.id: provider for provider in providers}
        return [self._row_dict(provider_by_id[provider_id]) for provider_id in page_ids if provider_id in provider_by_id], total

    def _row_dict(self, provider: Provider, item: ProviderItem | None = None) -> dict[str, Any]:
        item_rows = sorted(
            list(getattr(provider, "items", None) or []),
            key=lambda row: (float(getattr(row, "confidence", None) or 0), getattr(row, "id", 0)),
            reverse=True,
        )
        primary = item or (item_rows[0] if item_rows else None)
        item_summaries = [self._item_summary(row) for row in item_rows]
        return {
            "provider_id": provider.id,
            "provider_item_id": primary.id if primary else None,
            "company_name": provider.company_name,
            "canonical_name": provider.canonical_name,
            "identity_source": provider.identity_source,
            "identity_confidence": provider.identity_confidence,
            "aliases": provider.aliases or [],
            "cage": provider.cage,
            "uei": provider.uei,
            "website": provider.website,
            "contact_name": provider.contact_name,
            "email": provider.email,
            "phone": provider.phone,
            "provider_notes": provider.notes,
            "status": provider.status,
            "nsn": primary.nsn if primary else None,
            "fsc": primary.fsc if primary else None,
            "nomenclature": primary.nomenclature if primary else None,
            "relationship_type": primary.relationship_type if primary else None,
            "source": primary.source if primary else None,
            "source_url": primary.source_url if primary else None,
            "confidence": primary.confidence if primary else None,
            "item_notes": primary.notes if primary else None,
            "item_count": len(item_rows),
            "relationship_types": _unique([row.relationship_type for row in item_rows]),
            "sources": _unique([row.source for row in item_rows]),
            "nsns": _unique([row.nsn for row in item_rows]),
            "fscs": _unique([row.fsc for row in item_rows]),
            "item_summaries": item_summaries,
            "updated_at": provider.updated_at,
        }

    def _item_summary(self, item: ProviderItem) -> dict[str, Any]:
        return {
            "provider_item_id": item.id,
            "nsn": item.nsn,
            "fsc": item.fsc,
            "nomenclature": item.nomenclature,
            "relationship_type": item.relationship_type,
            "source": item.source,
            "source_url": item.source_url,
            "confidence": item.confidence,
            "notes": item.notes,
        }

    def import_csv(self, content: str) -> ProviderImportResult:
        result = ProviderImportResult()
        reader = csv.DictReader(io.StringIO(content or ""))
        if not reader.fieldnames:
            result.errors.append("CSV import did not include headers.")
            return result
        for index, row in enumerate(reader, start=2):
            try:
                payload = ProviderCreate(
                    company_name=row.get("company_name") or row.get("provider") or row.get("name") or "",
                    cage=row.get("cage") or row.get("cage_code"),
                    uei=row.get("uei"),
                    website=row.get("website") or row.get("url"),
                    contact_name=row.get("contact_name"),
                    email=row.get("email"),
                    phone=row.get("phone"),
                    notes=row.get("notes"),
                    item=ProviderItemCreate(
                        nsn=row.get("nsn"),
                        fsc=row.get("fsc"),
                        nomenclature=row.get("nomenclature") or row.get("item"),
                        relationship_type=row.get("type") or row.get("relationship_type") or "Unknown",
                        source=row.get("source") or "Import",
                        source_url=row.get("source_url") or row.get("url"),
                        notes=row.get("item_notes"),
                    ),
                )
                if not _clean(payload.company_name):
                    result.skipped += 1
                    result.errors.append(f"Line {index}: missing company_name.")
                    continue
                existing = self._find_provider(company_name=payload.company_name, cage=payload.cage, uei=payload.uei)
                self.create(payload)
                if existing:
                    result.updated += 1
                else:
                    result.inserted += 1
            except Exception as exc:
                self.db.rollback()
                result.errors.append(f"Line {index}: {exc}")
        return result

    def seed_from_vendor_leads(self, limit: int = 500) -> ProviderImportResult:
        result = ProviderImportResult()
        org_id = self._org_id()
        query = self.db.query(VendorLead).filter(VendorLead.company_name.is_not(None))
        if org_id is not None:
            query = query.filter(VendorLead.organization_id == org_id)
        leads = query.order_by(VendorLead.id.desc()).limit(max(min(limit, 2000), 1)).all()
        for lead in leads:
            try:
                source_type = _clean(getattr(lead, "source_type", None), 100) or "Workspace Vendor Lead"
                relationship_type = "Approved Source" if getattr(lead, "is_approved_source", False) else "Unknown"
                payload = ProviderCreate(
                    company_name=getattr(lead, "company_name", None) or "Unknown Provider",
                    cage=getattr(lead, "cage", None),
                    notes=getattr(lead, "notes", None),
                    item=ProviderItemCreate(
                        nsn=getattr(lead, "nsn", None),
                        relationship_type=relationship_type,
                        source=_display_source(source_type),
                        confidence=float(getattr(lead, "confidence", None) or 0),
                        notes=getattr(lead, "raw_text", None) or getattr(lead, "notes", None),
                    ),
                )
                existing = self._find_provider(company_name=payload.company_name, cage=payload.cage, uei=None)
                self.create(payload)
                if existing:
                    result.updated += 1
                else:
                    result.inserted += 1
            except Exception as exc:
                self.db.rollback()
                result.errors.append(f"Vendor lead {getattr(lead, 'id', '?')}: {exc}")
        return result
