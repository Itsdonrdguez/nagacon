from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.nsn_catalog import NsnEvidence
from app.models.provider import Provider


def clean_name(value: Any) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:300] if text else None


def normalize_cage(value: Any) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
    return text[:20] if text else None


def resolve_provider_identity(db: Session, provider: Provider) -> dict[str, Any]:
    cage = normalize_cage(getattr(provider, "cage", None))
    current_name = clean_name(getattr(provider, "company_name", None))
    evidence = _official_cage_evidence(db, cage) if cage else None

    official_name = clean_name((evidence.raw_payload or {}).get("COMPANY")) if evidence else None
    canonical_name = official_name or clean_name(getattr(provider, "canonical_name", None)) or current_name or "Unknown Provider"
    source = "PUB_LOG_P_CAGE" if official_name else getattr(provider, "identity_source", None) or "provider_record"
    confidence = 95.0 if official_name else float(getattr(provider, "identity_confidence", None) or 60.0)

    aliases = _merge_aliases(getattr(provider, "aliases", None), [current_name, official_name])
    placeholder = current_name and current_name.upper() in {"UNKNOWN PROVIDER", f"CAGE {cage}" if cage else ""}
    if official_name and (placeholder or current_name != official_name):
        provider.company_name = official_name
    provider.canonical_name = canonical_name
    provider.identity_source = source
    provider.identity_confidence = confidence
    provider.aliases = aliases
    if cage and not provider.cage:
        provider.cage = cage
    db.add(provider)
    return {
        "provider_id": provider.id,
        "canonical_name": provider.canonical_name,
        "cage": provider.cage,
        "identity_source": provider.identity_source,
        "identity_confidence": provider.identity_confidence,
        "aliases": aliases,
        "official_evidence": bool(evidence),
    }


def resolve_provider_identities(db: Session, *, organization_id: int | None = None, limit: int = 250) -> dict[str, Any]:
    query = db.query(Provider)
    if organization_id is not None:
        query = query.filter(Provider.organization_id == organization_id)
    providers = query.order_by(Provider.updated_at.desc()).limit(max(min(limit, 1000), 1)).all()
    resolved = [resolve_provider_identity(db, provider) for provider in providers]
    db.commit()
    return {"resolved": len(resolved), "items": resolved}


def _official_cage_evidence(db: Session, cage: str | None) -> NsnEvidence | None:
    if not cage:
        return None
    return (
        db.query(NsnEvidence)
        .filter(
            NsnEvidence.claim_type == "cage_profile",
            NsnEvidence.claim_value == cage,
            NsnEvidence.source_name == "PUB_LOG_P_CAGE",
        )
        .order_by(NsnEvidence.updated_at.desc())
        .first()
    )


def _merge_aliases(existing: Any, values: list[str | None]) -> list[str]:
    aliases: list[str] = []
    for value in list(existing or []) + values:
        text = clean_name(value)
        if not text:
            continue
        if text.lower() not in {item.lower() for item in aliases}:
            aliases.append(text)
    return aliases[:20]
