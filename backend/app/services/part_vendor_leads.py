from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.provider import Provider
from app.models.vendor import VendorLead, VendorQuote
from app.models.workspace import WorkspaceArtifact
from app.services.vendor_email_automation import generate_quote_request_email
from app.services.workspace_service import create_artifact

DEFAULT_QUOTE_STATUS = "NOT_REQUESTED"


def seed_vendor_leads_from_part_finder_result(
    db: Session,
    opp: Opportunity,
    result: dict[str, Any],
    *,
    organization_id: int | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    candidates = _build_part_finder_candidates(result, limit=limit)
    created = 0
    updated = 0
    skipped = 0
    seeded: list[dict[str, Any]] = []

    for candidate in candidates:
        if not candidate.get("company_name") and not candidate.get("cage"):
            skipped += 1
            continue
        rec = _find_existing_lead(db, opp.id, candidate)
        if rec:
            if _update_lead(rec, candidate, organization_id=organization_id or getattr(opp, "organization_id", None)):
                updated += 1
            seeded.append(_lead_seed_payload(rec, "updated"))
            continue

        rec = VendorLead(
            organization_id=organization_id or getattr(opp, "organization_id", None),
            opportunity_id=opp.id,
            source_type=candidate["source_type"],
            company_name=candidate.get("company_name"),
            cage=candidate.get("cage"),
            part_number=candidate.get("part_number"),
            nsn=candidate.get("nsn"),
            status="NEW",
            confidence=candidate.get("confidence") or 60,
            is_approved_source=bool(candidate.get("is_approved_source")),
            raw_text=candidate.get("raw_text"),
            notes=candidate.get("notes"),
        )
        db.add(rec)
        db.flush()
        created += 1
        seeded.append(_lead_seed_payload(rec, "created"))

    if created or updated:
        db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "candidate_count": len(candidates),
        "seeded": seeded,
    }


def seed_quotes_from_part_finder_leads(
    db: Session,
    opp: Opportunity,
    *,
    organization_id: int | None = None,
    min_confidence: int = 75,
    limit: int = 10,
) -> dict[str, Any]:
    org_id = organization_id or getattr(opp, "organization_id", None)
    query = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opp.id)
        .filter(VendorLead.cage.is_not(None), VendorLead.cage != "")
        .filter(VendorLead.confidence >= min_confidence)
        .filter(VendorLead.source_type.ilike("%PART_FINDER%"))
        .filter(VendorLead.status != "IGNORED")
    )
    if org_id is not None:
        query = query.filter(or_(VendorLead.organization_id == org_id, VendorLead.organization_id.is_(None)))
    leads = (
        query
        .order_by(VendorLead.is_approved_source.desc(), VendorLead.confidence.desc(), VendorLead.company_name.asc().nullslast())
        .limit(limit)
        .all()
    )

    created = 0
    updated = 0
    skipped = 0
    seeded: list[dict[str, Any]] = []
    for lead in leads:
        cage = _clean(lead.cage, 10)
        if not cage:
            skipped += 1
            continue
        part_number = _clean(lead.part_number, 80)
        quote = _find_existing_quote(db, opp.id, cage, part_number, organization_id=org_id)
        provider = _find_provider_for_cage(db, cage, organization_id=org_id)
        notes = _quote_notes_from_lead(lead)
        if quote:
            touched = _fill_quote_from_lead_and_provider(
                quote,
                lead,
                provider,
                organization_id=org_id,
                notes=notes,
            )
            if touched:
                quote.updated_at = datetime.utcnow()
                updated += 1
        else:
            quote = VendorQuote(
                organization_id=org_id,
                opportunity_id=opp.id,
                cage=cage,
                company_name=lead.company_name or getattr(provider, "company_name", None),
                part_number=part_number,
                status=DEFAULT_QUOTE_STATUS,
                notes=notes,
            )
            _fill_quote_from_lead_and_provider(
                quote,
                lead,
                provider,
                organization_id=org_id,
                notes=notes,
            )
            db.add(quote)
            db.flush()
            created += 1

        if lead.status != "SEEDED_TO_QUOTES":
            lead.status = "SEEDED_TO_QUOTES"
            lead.updated_at = datetime.utcnow()
        seeded.append(
            {
                "lead_id": lead.id,
                "quote_id": quote.id,
                "company_name": lead.company_name,
                "cage": cage,
                "part_number": part_number,
                "confidence": lead.confidence,
            }
        )

    if created or updated or seeded:
        db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "seedable_count": len(leads),
        "min_confidence": min_confidence,
        "seeded": seeded,
    }


def create_email_drafts_for_part_finder_quotes(
    db: Session,
    opp: Opportunity,
    quote_seed: dict[str, Any],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    seeded_quotes = quote_seed.get("seeded") or []
    created = 0
    skipped = 0
    errors: list[str] = []
    drafts: list[dict[str, Any]] = []
    existing_quote_ids = _existing_email_draft_quote_ids(db, opp.id)

    for item in seeded_quotes[:limit]:
        quote_id = item.get("quote_id")
        if not quote_id:
            skipped += 1
            continue
        if int(quote_id) in existing_quote_ids:
            skipped += 1
            continue
        quote = (
            db.query(VendorQuote)
            .filter(VendorQuote.id == int(quote_id), VendorQuote.opportunity_id == opp.id)
            .first()
        )
        if not quote:
            skipped += 1
            continue
        if not _clean(quote.email):
            skipped += 1
            continue
        try:
            draft = generate_quote_request_email(opportunity_id=opp.id, db=db, vendor_quote_id=quote.id)
            artifact = create_artifact(
                db,
                opp.id,
                "EMAIL_DRAFT",
                f"Vendor Email Draft - {draft.get('company_name') or quote.company_name or quote.cage or quote.id}",
                content_json={
                    **draft,
                    "target_vendor_name": draft.get("company_name") or quote.company_name,
                    "target_vendor_email": draft.get("to") or quote.email,
                    "vendor_quote_id": quote.id,
                    "generated_from": "part_finder_quote_auto_outreach",
                    "_meta": {
                        "artifact_type": "EMAIL_DRAFT",
                        "artifact_category": "OUTREACH",
                        "artifact_subtype": "PART_FINDER_QUOTE_EMAIL",
                        "artifact_status": "DRAFT",
                    },
                    "_outreach_log": [
                        {
                            "action": "draft_created",
                            "timestamp": datetime.utcnow().isoformat(),
                            "recipient": draft.get("to") or quote.email,
                            "vendor_name": draft.get("company_name") or quote.company_name,
                            "source": "part_finder_quote_auto_outreach",
                        }
                    ],
                },
            )
            created += 1
            existing_quote_ids.add(quote.id)
            drafts.append(
                {
                    "artifact_id": artifact.id,
                    "quote_id": quote.id,
                    "to": draft.get("to") or quote.email,
                    "company_name": draft.get("company_name") or quote.company_name,
                }
            )
        except Exception as exc:
            db.rollback()
            errors.append(f"Quote {quote_id}: {exc}")

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "drafts": drafts,
    }


def _build_part_finder_candidates(result: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    part = result.get("part") or {}
    nsn = _clean(part.get("nsn"))
    first_part_number = _first(part.get("part_numbers") or [])
    candidates: dict[tuple[str, str | None], dict[str, Any]] = {}

    def merge_candidate(row: dict[str, Any]) -> None:
        company_name = _clean(row.get("company_name"), 200)
        cage = _clean(row.get("cage"), 10)
        part_number = _clean(row.get("part_number"), 80)
        if not company_name and not cage:
            return
        key = ((cage or company_name or "").upper(), part_number)
        item = candidates.setdefault(
            key,
            {
                "company_name": company_name,
                "cage": cage,
                "part_number": part_number,
                "nsn": nsn,
                "confidence": 0,
                "is_approved_source": False,
                "evidence_types": set(),
                "notes_parts": [],
                "raw_parts": [],
            },
        )
        if company_name and not item.get("company_name"):
            item["company_name"] = company_name
        item["confidence"] = max(int(item.get("confidence") or 0), int(row.get("confidence") or 0))
        item["is_approved_source"] = bool(item.get("is_approved_source") or row.get("is_approved_source"))
        if row.get("evidence_type"):
            item["evidence_types"].add(row["evidence_type"])
        if row.get("notes"):
            item["notes_parts"].append(row["notes"])
        if row.get("raw_text"):
            item["raw_parts"].append(row["raw_text"])

    for provider in (result.get("providers") or [])[:limit]:
        roles = [str(role) for role in (provider.get("roles") or []) if role]
        sources = [str(source) for source in (provider.get("sources") or []) if source]
        role_text = ", ".join(roles) or "Provider"
        is_approved = any("approved" in role.lower() for role in roles) or any("approved" in source.lower() for source in sources)
        merge_candidate(
            {
                "company_name": provider.get("name"),
                "cage": provider.get("cage"),
                "part_number": first_part_number,
                "confidence": _provider_confidence(provider, is_approved=is_approved),
                "is_approved_source": is_approved,
                "evidence_type": "PART_FINDER_PROVIDER",
                "notes": f"Part Finder provider candidate. Roles: {role_text}. Sources: {', '.join(sources) or 'NSN catalog/provider evidence'}.",
                "raw_text": f"Part Finder provider for NSN {nsn}; roles={roles}; sources={sources}",
            }
        )

    for awardee in (result.get("awardees") or [])[:limit]:
        award_count = int(awardee.get("award_count") or 0)
        amount = awardee.get("total_award_amount") or 0
        merge_candidate(
            {
                "company_name": awardee.get("name"),
                "cage": awardee.get("cage"),
                "part_number": first_part_number,
                "confidence": min(92, 62 + min(award_count * 6, 24)),
                "is_approved_source": False,
                "evidence_type": "PART_FINDER_AWARDEE",
                "notes": (
                    "Part Finder awardee evidence. "
                    f"Award count: {award_count}. Total amount: {amount}. "
                    f"Latest award: {_clean(awardee.get('latest_award_date')) or 'not reported'}."
                ),
                "raw_text": f"Part Finder awardee for NSN {nsn}; sources={awardee.get('sources') or []}",
            }
        )

    output: list[dict[str, Any]] = []
    for item in candidates.values():
        evidence_types = sorted(item.pop("evidence_types"))
        notes_parts = _unique(item.pop("notes_parts"))
        raw_parts = _unique(item.pop("raw_parts"))
        item["source_type"] = _source_type_from_evidence(evidence_types)
        item["notes"] = " ".join(notes_parts)[:4000] or None
        item["raw_text"] = " | ".join(raw_parts)[:4000] or None
        output.append(item)

    return sorted(output, key=lambda row: (-(row.get("confidence") or 0), row.get("company_name") or row.get("cage") or ""))[:limit]


def _find_existing_lead(db: Session, opportunity_id: int, candidate: dict[str, Any]) -> VendorLead | None:
    cage = candidate.get("cage")
    company_name = candidate.get("company_name")
    part_number = candidate.get("part_number")
    query = db.query(VendorLead).filter(VendorLead.opportunity_id == opportunity_id)
    if cage:
        query = query.filter(func.upper(func.coalesce(VendorLead.cage, "")) == cage.upper())
    else:
        query = query.filter(VendorLead.cage.is_(None))
        if company_name:
            query = query.filter(func.lower(func.coalesce(VendorLead.company_name, "")) == company_name.lower())
    if part_number:
        query = query.filter(VendorLead.part_number == part_number)
    else:
        query = query.filter(VendorLead.part_number.is_(None))
    return query.first()


def _find_existing_quote(
    db: Session,
    opportunity_id: int,
    cage: str,
    part_number: str | None,
    *,
    organization_id: int | None = None,
) -> VendorQuote | None:
    query = (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opportunity_id)
        .filter(func.upper(func.coalesce(VendorQuote.cage, "")) == cage.upper())
    )
    if organization_id is not None:
        query = query.filter(or_(VendorQuote.organization_id == organization_id, VendorQuote.organization_id.is_(None)))
    if part_number:
        query = query.filter(VendorQuote.part_number == part_number)
    else:
        query = query.filter(VendorQuote.part_number.is_(None))
    return query.first()


def _existing_email_draft_quote_ids(db: Session, opportunity_id: int) -> set[int]:
    artifacts = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opportunity_id,
            WorkspaceArtifact.artifact_type == "EMAIL_DRAFT",
        )
        .all()
    )
    quote_ids: set[int] = set()
    for artifact in artifacts:
        content = artifact.content_json or {}
        quote_id = content.get("vendor_quote_id")
        generated_from = content.get("generated_from")
        subtype = (content.get("_meta") or {}).get("artifact_subtype")
        if quote_id and (generated_from == "part_finder_quote_auto_outreach" or subtype == "PART_FINDER_QUOTE_EMAIL"):
            try:
                quote_ids.add(int(quote_id))
            except (TypeError, ValueError):
                continue
    return quote_ids


def _find_provider_for_cage(db: Session, cage: str, *, organization_id: int | None = None) -> Provider | None:
    query = db.query(Provider).filter(func.upper(func.coalesce(Provider.cage, "")) == cage.upper())
    if organization_id is not None:
        query = query.filter(or_(Provider.organization_id == organization_id, Provider.organization_id.is_(None)))
    return (
        query
        .order_by(Provider.organization_id.desc().nullslast(), Provider.updated_at.desc(), Provider.id.desc())
        .first()
    )


def _fill_quote_from_lead_and_provider(
    quote: VendorQuote,
    lead: VendorLead,
    provider: Provider | None,
    *,
    organization_id: int | None = None,
    notes: str | None = None,
) -> bool:
    touched = False
    if quote.organization_id is None and organization_id is not None:
        quote.organization_id = organization_id
        touched = True
    if not quote.company_name:
        quote.company_name = lead.company_name or getattr(provider, "company_name", None)
        touched = bool(quote.company_name) or touched
    if provider:
        for attr in ["contact_name", "email", "phone"]:
            value = getattr(provider, attr, None)
            if value and not getattr(quote, attr, None):
                setattr(quote, attr, value)
                touched = True
        provider_note = _provider_contact_note(provider)
        notes = _merge_text(notes, provider_note)
    merged_notes = _merge_text(quote.notes, notes)
    if merged_notes != quote.notes:
        quote.notes = merged_notes
        touched = True
    return touched


def _update_lead(rec: VendorLead, candidate: dict[str, Any], *, organization_id: int | None = None) -> bool:
    touched = False
    for attr in ["company_name", "cage", "part_number", "nsn"]:
        value = candidate.get(attr)
        if value and not getattr(rec, attr, None):
            setattr(rec, attr, value)
            touched = True
    if organization_id is not None and rec.organization_id is None:
        rec.organization_id = organization_id
        touched = True
    if candidate.get("confidence") and int(candidate["confidence"]) > int(rec.confidence or 0):
        rec.confidence = int(candidate["confidence"])
        touched = True
    if candidate.get("is_approved_source") and not rec.is_approved_source:
        rec.is_approved_source = True
        touched = True
    source_type = _combine_source_types(rec.source_type, candidate.get("source_type"))
    if source_type != rec.source_type:
        rec.source_type = source_type
        touched = True
    notes = _merge_text(rec.notes, candidate.get("notes"))
    if notes != rec.notes:
        rec.notes = notes
        touched = True
    raw_text = _merge_text(rec.raw_text, candidate.get("raw_text"))
    if raw_text != rec.raw_text:
        rec.raw_text = raw_text
        touched = True
    if touched:
        rec.updated_at = datetime.utcnow()
    return touched


def _source_type_from_evidence(evidence_types: list[str]) -> str:
    if "PART_FINDER_PROVIDER" in evidence_types and "PART_FINDER_AWARDEE" in evidence_types:
        return "PART_FINDER_PROVIDER_AWARDEE"
    if "PART_FINDER_AWARDEE" in evidence_types:
        return "PART_FINDER_AWARDEE"
    return "PART_FINDER_PROVIDER"


def _combine_source_types(left: str | None, right: str | None) -> str:
    values = {item for item in [left, right] if item}
    if {"PART_FINDER_PROVIDER", "PART_FINDER_AWARDEE"}.issubset(values) or "PART_FINDER_PROVIDER_AWARDEE" in values:
        values.discard("PART_FINDER_PROVIDER")
        values.discard("PART_FINDER_AWARDEE")
        values.add("PART_FINDER_PROVIDER_AWARDEE")
    return "+".join(sorted(values)) if values else "PART_FINDER_PROVIDER"


def _provider_confidence(provider: dict[str, Any], *, is_approved: bool) -> int:
    try:
        raw = int(float(provider.get("confidence") or 0))
    except (TypeError, ValueError):
        raw = 0
    if raw <= 0:
        raw = 78 if provider.get("cage") else 68
    if is_approved:
        raw += 8
    return min(max(raw, 55), 98)


def _lead_seed_payload(rec: VendorLead, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "lead_id": rec.id,
        "company_name": rec.company_name,
        "cage": rec.cage,
        "source_type": rec.source_type,
        "confidence": rec.confidence,
    }


def _quote_notes_from_lead(lead: VendorLead) -> str:
    parts = [
        "Auto-created from Part Finder vendor evidence.",
        f"Lead source: {lead.source_type}." if lead.source_type else None,
        f"Lead confidence: {lead.confidence}." if lead.confidence is not None else None,
        f"NSN: {lead.nsn}." if lead.nsn else None,
        "Approved-source signal present." if lead.is_approved_source else None,
        lead.notes,
    ]
    return " ".join(part for part in parts if part)[:4000]


def _provider_contact_note(provider: Provider) -> str | None:
    parts = [
        "Provider contact enrichment.",
        f"Website: {provider.website}." if provider.website else None,
        f"Email: {provider.email}." if provider.email else None,
        f"Phone: {provider.phone}." if provider.phone else None,
    ]
    return " ".join(part for part in parts if part) or None


def _merge_text(current: str | None, incoming: str | None, *, max_len: int = 4000) -> str | None:
    current_clean = _clean(current)
    incoming_clean = _clean(incoming)
    if not incoming_clean:
        return current_clean
    if not current_clean:
        return incoming_clean[:max_len]
    if incoming_clean.lower() in current_clean.lower():
        return current_clean
    return f"{current_clean} {incoming_clean}"[:max_len]


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _first(values: list[Any]) -> str | None:
    for value in values:
        text = _clean(value, 80)
        if text:
            return text
    return None


def _clean(value: Any, max_len: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_len] if max_len else text
