from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.nsn_catalog import NsnAwardEvidence, NsnReference
from app.models.price_history import PriceHistory
from app.models.provider import Provider, ProviderItem
from app.services.nsn_catalog.normalizer import normalize_cage, normalize_nsn
from app.services.nsn_catalog.provider_seeding import catalog_reference_role


@dataclass
class VendorCandidate:
    key: str
    company_name: str
    cage: str | None = None
    score: float = 0
    roles: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    reasons: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provider_id: int | None = None
    website: str | None = None

    def add_score(self, amount: float, reason: str) -> None:
        self.score += amount
        if reason and reason not in self.reasons:
            self.reasons.append(reason)


def build_vendor_recommendations(db: Session, nsn: str, *, limit: int = 25) -> list[dict[str, Any]]:
    target = normalize_nsn(nsn)
    if not target:
        return []

    candidates: dict[str, VendorCandidate] = {}

    for row in _catalog_references(db, target.compact):
        candidate = _candidate_for(
            candidates,
            company_name=row.company_name or (f"CAGE {row.cage}" if row.cage else "Unknown Catalog Source"),
            cage=row.cage,
        )
        role = catalog_reference_role(row)
        candidate.roles.add(role)
        candidate.sources.add(row.source_name or "Catalog")
        candidate.add_score(45, "Catalog reference links this source to the NSN.")
        if row.cage:
            candidate.add_score(10, "Catalog reference includes a CAGE code.")
        if row.part_number:
            candidate.add_score(10, "Catalog reference includes a part/reference number.")
        if role == "OEM Candidate":
            candidate.add_score(15, "Reference relationship indicates manufacturer/OEM-style evidence.")
        candidate.evidence.append(
            {
                "source": row.source_name,
                "type": "catalog_reference",
                "cage": row.cage,
                "part_number": row.part_number,
                "relationship_type": row.relationship_type,
                "reference_type": row.reference_type,
                "confidence": row.confidence,
            }
        )

    for provider, item in _provider_rows(db, target.nsn):
        candidate = _candidate_for(candidates, company_name=provider.company_name, cage=provider.cage)
        candidate.provider_id = provider.id
        candidate.website = provider.website or candidate.website
        candidate.roles.add(item.relationship_type or "Provider Match")
        candidate.sources.add(item.source or "Provider")
        candidate.add_score(35, "Existing provider record is tied to this NSN.")
        if item.confidence:
            candidate.add_score(min(float(item.confidence), 100) * 0.15, "Provider item has confidence evidence.")
        if provider.website:
            candidate.add_score(5, "Provider has a website/contact path.")
        candidate.evidence.append(
            {
                "source": item.source,
                "type": "provider_item",
                "provider_id": provider.id,
                "relationship_type": item.relationship_type,
                "confidence": item.confidence,
                "notes": item.notes,
            }
        )

    for row in _award_rows(db, target.nsn):
        candidate = _candidate_for(candidates, company_name=row.recipient_name or "Unknown Awardee", cage=row.recipient_cage)
        candidate.roles.add("Historical Awardee")
        candidate.sources.add(row.source_system or "Award History")
        candidate.add_score(25, "Historical award evidence exists for this NSN.")
        if row.match_confidence == "high":
            candidate.add_score(15, "Award match confidence is high.")
        elif row.match_confidence == "medium":
            candidate.add_score(8, "Award match confidence is medium.")
        if row.award_amount:
            candidate.add_score(5, "Award includes value history.")
        candidate.evidence.append(
            {
                "source": row.source_system,
                "type": "award_history",
                "award_id": row.award_id,
                "piid": row.piid,
                "award_date": row.award_date,
                "award_amount": row.award_amount,
                "match_confidence": row.match_confidence,
                "match_reasons": row.match_reasons,
            }
        )

    for row in _nsn_award_rows(db, target.compact):
        candidate = _candidate_for(candidates, company_name=row.recipient_name or "Unknown Awardee", cage=row.recipient_cage)
        candidate.roles.add("NSN Award Evidence")
        candidate.sources.add(row.source_system or "Award Evidence")
        candidate.add_score(22, "Standalone NSN award evidence exists.")
        if row.match_confidence == "high":
            candidate.add_score(15, "NSN award evidence has high confidence.")
        elif row.match_confidence == "medium":
            candidate.add_score(8, "NSN award evidence has medium confidence.")
        candidate.evidence.append(
            {
                "source": row.source_system,
                "type": "nsn_award_evidence",
                "award_id": row.award_id,
                "piid": row.piid,
                "award_date": row.award_date,
                "award_amount": row.award_amount,
                "matched_by": row.matched_by,
                "match_confidence": row.match_confidence,
                "match_reasons": row.match_reasons,
            }
        )

    for row in _price_rows(db, target.nsn):
        candidate = _candidate_for(candidates, company_name=row.supplier_name or "Unknown Price Source", cage=row.cage)
        candidate.roles.add("Price History Supplier")
        candidate.sources.add(row.source_label or "Price History")
        candidate.add_score(18, "Pricing history exists for this NSN.")
        if row.unit_price is not None:
            candidate.add_score(5, "Unit price was extracted.")
        if row.confidence:
            candidate.add_score(min(float(row.confidence), 100) * 0.1, "Price extraction has confidence evidence.")
        candidate.evidence.append(
            {
                "source": row.source_label,
                "type": "price_history",
                "award_id": row.award_id,
                "award_date": row.award_date,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "total_price": row.total_price,
                "confidence": row.confidence,
            }
        )

    return [_candidate_payload(candidate) for candidate in _ranked(candidates.values(), limit=limit)]


def _catalog_references(db: Session, compact_nsn: str) -> list[NsnReference]:
    return (
        db.query(NsnReference)
        .filter(NsnReference.compact_nsn == compact_nsn)
        .filter((NsnReference.cage.is_not(None)) | (NsnReference.company_name.is_not(None)))
        .order_by(NsnReference.confidence.desc().nullslast(), NsnReference.company_name.asc().nullslast())
        .limit(250)
        .all()
    )


def _provider_rows(db: Session, nsn: str) -> list[tuple[Provider, ProviderItem]]:
    return (
        db.query(Provider, ProviderItem)
        .join(ProviderItem, ProviderItem.provider_id == Provider.id)
        .filter(ProviderItem.nsn == nsn)
        .order_by(ProviderItem.confidence.desc().nullslast(), Provider.company_name.asc())
        .limit(250)
        .all()
    )


def _award_rows(db: Session, nsn: str) -> list[AwardHistory]:
    return (
        db.query(AwardHistory)
        .filter(AwardHistory.nsn == nsn)
        .order_by(AwardHistory.match_score.desc().nullslast(), AwardHistory.award_date.desc().nullslast())
        .limit(250)
        .all()
    )


def _nsn_award_rows(db: Session, compact_nsn: str) -> list[NsnAwardEvidence]:
    return (
        db.query(NsnAwardEvidence)
        .filter(NsnAwardEvidence.compact_nsn == compact_nsn)
        .order_by(NsnAwardEvidence.match_score.desc().nullslast(), NsnAwardEvidence.award_date.desc().nullslast())
        .limit(250)
        .all()
    )


def _price_rows(db: Session, nsn: str) -> list[PriceHistory]:
    return (
        db.query(PriceHistory)
        .filter(PriceHistory.nsn == nsn)
        .order_by(PriceHistory.confidence.desc().nullslast(), PriceHistory.award_date.desc().nullslast())
        .limit(250)
        .all()
    )


def _candidate_for(candidates: dict[str, VendorCandidate], *, company_name: str, cage: str | None) -> VendorCandidate:
    clean_cage = normalize_cage(cage) or None
    clean_name = " ".join(str(company_name or "").split()) or (f"CAGE {clean_cage}" if clean_cage else "Unknown Vendor")
    key = f"cage:{clean_cage}" if clean_cage else f"name:{clean_name.lower()}"
    if key not in candidates:
        candidates[key] = VendorCandidate(key=key, company_name=clean_name, cage=clean_cage)
    candidate = candidates[key]
    if clean_name and candidate.company_name.startswith("CAGE ") and not clean_name.startswith("CAGE "):
        candidate.company_name = clean_name
    return candidate


def _ranked(candidates: list[VendorCandidate] | Any, *, limit: int) -> list[VendorCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            0 if candidate.cage else 1,
            candidate.company_name.lower(),
        ),
    )[: max(min(limit, 100), 1)]


def _candidate_payload(candidate: VendorCandidate) -> dict[str, Any]:
    score = round(min(candidate.score, 100.0), 2)
    return {
        "company_name": candidate.company_name,
        "cage": candidate.cage,
        "provider_id": candidate.provider_id,
        "website": candidate.website,
        "score": score,
        "confidence": _confidence_label(score),
        "roles": sorted(candidate.roles),
        "sources": sorted(candidate.sources),
        "reasons": candidate.reasons[:8],
        "evidence": candidate.evidence[:10],
    }


def _confidence_label(score: float) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"
