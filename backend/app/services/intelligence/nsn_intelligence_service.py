from __future__ import annotations

import re
from datetime import datetime
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.models.award_history import AwardHistory
from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.price_history import PriceHistory
from app.models.provider import Provider, ProviderItem
from app.models.vendor import VendorLead
from app.models.workspace import WorkspaceArtifact
from app.services.providers.pdf_cage_extractor import seed_vendor_leads_from_providers
from app.services.intelligence.sam_contracts_client import search_sam_contract_awards_for_target
from app.services.research.usaspending_research_service import (
    search_usaspending_for_opportunity,
    seed_usaspending_vendors_into_leads,
)
from app.services.workspace_service import create_artifact, ensure_parsed


def _clean(value: Any, max_len: int | None = None) -> str:
    text = "" if value is None else re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return ""
    return text[:max_len] if max_len else text


def _normalize_nsn(value: str | None) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 13:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:]}"
    return ""


def _compact_nsn(nsn: str | None) -> str:
    return re.sub(r"\D+", "", nsn or "")


def _dedupe(values: list[str]) -> list[str]:
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


def _keywords_from_text(text: str, limit: int = 8) -> list[str]:
    stop = {
        "and", "the", "for", "with", "from", "item", "nsn", "rfq", "dla",
        "dibbs", "solicitation", "request", "quote", "number", "supply",
    }
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", text.upper())
    out: list[str] = []
    for token in tokens:
        if token.lower() in stop or token.isdigit() or token in out or re.match(r"^SPE[A-Z0-9]+", token):
            continue
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _clean_nomenclature(value: str | None) -> str:
    text = _clean(value, 300)
    text = re.sub(r"\s+-\s+SPE[A-Z0-9\-]+$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+-\s+\d{4}[- ]?\d{2}[- ]?\d{3}[- ]?\d{4}$", "", text)
    return _clean(text, 300)


def _part_from_notes(notes: str | None) -> str:
    match = re.search(r"\bPart number:\s*([^;,\n]+)", notes or "", re.IGNORECASE)
    return _clean(match.group(1), 120) if match else ""


def _looks_like_part_number(value: str | None) -> bool:
    text = _clean(value, 120)
    if not text:
        return False
    if len(text) < 2 or len(text) > 80:
        return False
    if re.search(r"(https?|www\.|officeapps|dla\.mil)", text, re.IGNORECASE):
        return False
    return bool(re.search(r"\d", text) or re.search(r"[./_-]", text))


def _extract_document_source_hints(text: str) -> dict[str, list[str]]:
    part_numbers: list[str] = []
    manufacturers: list[str] = []
    cages: list[str] = []
    if not text:
        return {"part_numbers": [], "manufacturer_names": [], "manufacturer_cages": []}

    patterns = [
        re.compile(
            r"CAGE\s*[:#-]?\s*(?P<cage>[0-9A-Z]{5}).{0,160}?"
            r"(?:PART\s*(?:NUMBER|NO\.?|#)|P/N)\s*[:#-]?\s*(?P<part>[A-Z0-9./_-]{2,80}).{0,200}?"
            r"(?:COMPANY\s*NAME|MANUFACTURER|MFR|NAME)\s*[:#-]?\s*(?P<name>[^;\n|]{2,120})",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"(?:COMPANY\s*NAME|MANUFACTURER|MFR|NAME)\s*[:#-]?\s*(?P<name>[^;\n|]{2,120}).{0,200}?"
            r"CAGE\s*[:#-]?\s*(?P<cage>[0-9A-Z]{5}).{0,160}?"
            r"(?:PART\s*(?:NUMBER|NO\.?|#)|P/N)\s*[:#-]?\s*(?P<part>[A-Z0-9./_-]{2,80})",
            re.IGNORECASE | re.DOTALL,
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            cage = _clean(match.group("cage"), 20).upper()
            part = _clean(match.group("part"), 120)
            name = _clean(match.group("name"), 240)
            if cage:
                cages.append(cage)
            if _looks_like_part_number(part):
                part_numbers.append(part)
            if name and not re.search(r"(solicitation|policy statements|feedback|cage|part number)", name, re.IGNORECASE):
                manufacturers.append(name)

    for match in re.finditer(r"(?:PART\s*(?:NUMBER|NO\.?|#)|P/N|PN)\s*[:#-]?\s*([A-Z0-9./_-]{2,80})", text, re.IGNORECASE):
        part = _clean(match.group(1), 120)
        if _looks_like_part_number(part):
            part_numbers.append(part)

    return {
        "part_numbers": _dedupe(part_numbers),
        "manufacturer_names": _dedupe(manufacturers),
        "manufacturer_cages": _dedupe(cages),
    }


def build_nsn_research_target(db: Session, opp: Opportunity) -> dict[str, Any]:
    parsed = ensure_parsed(db, opp) or {}
    raw_nsn = (
        _clean(parsed.get("nsn"))
        or _normalize_nsn(getattr(opp, "solicitation_number", None))
        or _normalize_nsn(getattr(opp, "source_opportunity_id", None))
        or _normalize_nsn(getattr(opp, "title", None))
        or _normalize_nsn(getattr(opp, "raw_text", None))
    )
    nsn = _normalize_nsn(raw_nsn) or raw_nsn
    fsc = _clean(parsed.get("fsc") or getattr(opp, "fsc", None)) or (_compact_nsn(nsn)[:4] if nsn else "")
    nomenclature = (
        _clean_nomenclature(parsed.get("nomenclature"))
        or _clean_nomenclature(parsed.get("item_description"))
        or _clean_nomenclature(getattr(opp, "display_title", None))
        or _clean_nomenclature(getattr(opp, "title", None))
    )
    part_numbers = _dedupe([_clean(x) for x in (parsed.get("part_numbers") or [])])
    manufacturers = _dedupe([_clean(x) for x in (parsed.get("manufacturers") or [])])
    approved_sources = parsed.get("approved_sources") or []
    approved_cages = _dedupe([_clean(row.get("cage")) for row in approved_sources if isinstance(row, dict)])
    approved_names = _dedupe([_clean(row.get("company_name")) for row in approved_sources if isinstance(row, dict)])

    provider_rows = (
        db.query(Provider, ProviderItem)
        .join(ProviderItem, ProviderItem.provider_id == Provider.id)
        .filter(ProviderItem.nsn == nsn)
        .order_by(ProviderItem.confidence.desc().nullslast(), Provider.company_name.asc())
        .all()
        if nsn
        else []
    )
    for provider, item in provider_rows:
        if provider.cage:
            approved_cages.append(provider.cage)
        if provider.company_name:
            approved_names.append(provider.company_name)
        if item.notes:
            part = _part_from_notes(item.notes)
            if part:
                part_numbers.append(part)

    lead_rows = db.query(VendorLead).filter(VendorLead.opportunity_id == opp.id).all()
    for lead in lead_rows:
        if lead.cage:
            approved_cages.append(lead.cage)
        if lead.company_name:
            approved_names.append(lead.company_name)
        if lead.part_number:
            part_numbers.append(lead.part_number)
        part = _part_from_notes(lead.notes or lead.raw_text)
        if part:
            part_numbers.append(part)

    price_rows = db.query(PriceHistory).filter(PriceHistory.opportunity_id == opp.id).all()
    for row in price_rows:
        if row.cage:
            approved_cages.append(row.cage)
        if row.supplier_name:
            approved_names.append(row.supplier_name)

    file_rows = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc(), OpportunityFile.id.desc())
        .limit(6)
        .all()
    )
    for file in file_rows:
        hints = _extract_document_source_hints(getattr(file, "extracted_text", None) or "")
        part_numbers.extend(hints["part_numbers"])
        approved_names.extend(hints["manufacturer_names"])
        approved_cages.extend(hints["manufacturer_cages"])

    part_numbers = [part for part in _dedupe(part_numbers) if _looks_like_part_number(part)]

    keywords = _dedupe(
        [nsn, _compact_nsn(nsn), fsc]
        + _keywords_from_text(nomenclature, limit=8)
        + part_numbers[:6]
        + approved_names[:4]
        + manufacturers[:4]
    )
    return {
        "opportunity_id": opp.id,
        "source": getattr(opp, "source", None),
        "solicitation_number": getattr(opp, "solicitation_number", None),
        "agency": getattr(opp, "agency", None),
        "nsn": nsn or None,
        "nsn_compact": _compact_nsn(nsn) or None,
        "niin": (_compact_nsn(nsn)[4:] if len(_compact_nsn(nsn)) == 13 else None),
        "fsc": fsc or None,
        "nomenclature": nomenclature or None,
        "part_numbers": _dedupe(part_numbers),
        "manufacturer_names": _dedupe(manufacturers + approved_names),
        "manufacturer_cages": _dedupe(approved_cages),
        "keywords": keywords[:20],
    }


def _vendor_profiles_from_awards(vendors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for vendor in vendors[:10]:
        award_amounts = []
        for award in vendor.get("sample_awards") or []:
            try:
                amount = float(award.get("award_amount") or 0)
            except Exception:
                amount = 0
            if amount > 0:
                award_amounts.append(amount)
        profiles.append(
            {
                "vendor_name": vendor.get("vendor"),
                "cage": vendor.get("cage"),
                "award_count": vendor.get("award_count", 0),
                "total_award_amount": vendor.get("total_award_amount", 0),
                "average_sample_award": round(mean(award_amounts), 2) if award_amounts else None,
                "latest_award_date": vendor.get("last_award_date"),
                "source_type": vendor.get("source_type") or "USAspending",
                "match_reasons": vendor.get("match_reasons") or [],
                "sample_awards": (vendor.get("sample_awards") or [])[:3],
            }
        )
    return profiles


def _pricing_summary(db: Session, opp_id: int) -> dict[str, Any]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.opportunity_id == opp_id)
        .order_by(PriceHistory.award_date.desc().nullslast(), PriceHistory.id.desc())
        .limit(25)
        .all()
    )
    unit_prices = [float(row.unit_price) for row in rows if row.unit_price is not None and row.unit_price > 0]
    totals = [float(row.total_price) for row in rows if row.total_price is not None and row.total_price > 0]
    return {
        "price_fact_count": len(rows),
        "unit_price_low": round(min(unit_prices), 4) if unit_prices else None,
        "unit_price_high": round(max(unit_prices), 4) if unit_prices else None,
        "unit_price_average": round(mean(unit_prices), 4) if unit_prices else None,
        "award_amount_low": round(min(totals), 2) if totals else None,
        "award_amount_high": round(max(totals), 2) if totals else None,
        "award_amount_average": round(mean(totals), 2) if totals else None,
        "latest_items": [
            {
                "supplier_name": row.supplier_name,
                "cage": row.cage,
                "award_id": row.award_id,
                "award_date": row.award_date,
                "unit_price": row.unit_price,
                "total_price": row.total_price,
                "source": row.source_label,
            }
            for row in rows[:8]
        ],
    }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _award_dedupe_key(source_system: str, row: dict[str, Any]) -> str:
    parts = [
        source_system,
        row.get("award_id") or row.get("piid") or "",
        row.get("modification_number") or "",
        row.get("recipient_name") or "",
        row.get("award_date") or row.get("start_date") or "",
        str(row.get("award_amount") or ""),
    ]
    key = "|".join(_clean(part, 80).lower() for part in parts if _clean(part))
    return key[:360] or f"{source_system.lower()}|unknown"


def _confidence_label(score: float | None, reasons: list[str] | None = None) -> str:
    reasons_text = " ".join(reasons or []).lower()
    numeric = float(score or 0)
    if numeric >= 70 or "nsn" in reasons_text or "part_number_match" in reasons_text or "part number" in reasons_text:
        return "exact"
    if numeric >= 45 or "manufacturer" in reasons_text or "approved_source" in reasons_text or "strict" in reasons_text:
        return "strong"
    if numeric >= 30 or "psc" in reasons_text or "fsc" in reasons_text:
        return "broad"
    return "weak"


def _usaspending_score(row: dict[str, Any]) -> float:
    base = float(row.get("relevance_score") or 0)
    if row.get("strict_seedable_product_evidence"):
        base += 35
    elif row.get("seedable_product_evidence"):
        base += 25
    if row.get("match_category") == "product":
        base += 10
    return round(min(base, 100), 2)


def _unique_usaspending_awards(research: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ["strict_seedable_product_like_awards", "seedable_product_like_awards", "product_like_awards"]:
        rows.extend(research.get(key) or [])
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (-_usaspending_score(item), item.get("recipient_name") or "")):
        key = (
            _clean(row.get("award_id")).lower(),
            _clean(row.get("recipient_name")).lower(),
            _clean(row.get("start_date")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _persist_award_row(db: Session, opp: Opportunity, target: dict[str, Any], values: dict[str, Any]) -> str:
    dedupe_key = _award_dedupe_key(values["source_system"], values)
    existing = (
        db.query(AwardHistory)
        .filter(AwardHistory.opportunity_id == opp.id, AwardHistory.dedupe_key == dedupe_key)
        .first()
    )
    payload = {
        **values,
        "organization_id": getattr(opp, "organization_id", None),
        "opportunity_id": opp.id,
        "dedupe_key": dedupe_key,
        "nsn": target.get("nsn"),
        "fsc": target.get("fsc"),
        "updated_at": datetime.utcnow(),
    }
    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        return "updated"
    db.add(AwardHistory(**payload))
    return "created"


def persist_award_history(
    db: Session,
    opp: Opportunity,
    target: dict[str, Any],
    research: dict[str, Any],
    sam_validation: dict[str, Any],
) -> dict[str, Any]:
    created = 0
    updated = 0
    skipped = 0

    usa_rows = _unique_usaspending_awards(research)
    for row in usa_rows[:30]:
        score = _usaspending_score(row)
        reasons = list(row.get("relevance_reasons") or [])
        if row.get("strict_seedable_product_evidence"):
            reasons.append("strict_product_match")
        elif row.get("seedable_product_evidence"):
            reasons.append("seedable_product_match")
        confidence = _confidence_label(score, reasons)
        if confidence == "weak":
            skipped += 1
            continue
        result = _persist_award_row(
            db,
            opp,
            target,
            {
                "source_system": "USAspending",
                "award_id": _clean(row.get("award_id"), 160) or None,
                "piid": None,
                "modification_number": None,
                "solicitation_id": None,
                "recipient_name": _clean(row.get("recipient_name"), 300) or None,
                "recipient_cage": _clean(row.get("cage"), 20) or None,
                "recipient_uei": None,
                "awarding_agency": _clean(row.get("awarding_agency"), 240) or None,
                "contracting_department": None,
                "contracting_subtier": None,
                "award_date": _clean(row.get("start_date"), 40) or None,
                "award_amount": _to_float(row.get("award_amount")),
                "description": _clean(row.get("description")) or None,
                "psc_code": target.get("fsc"),
                "naics_code": None,
                "match_score": score,
                "match_confidence": confidence,
                "match_reasons": reasons,
                "raw_payload": row.get("raw") or row,
            },
        )
        created += int(result == "created")
        updated += int(result == "updated")

    sam_rows = sam_validation.get("validated_records") or sam_validation.get("top_records") or []
    for row in sam_rows[:30]:
        score = _to_float(row.get("match_score")) or 0
        reasons = row.get("match_reasons") or []
        confidence = _confidence_label(score, reasons)
        if confidence == "weak":
            skipped += 1
            continue
        result = _persist_award_row(
            db,
            opp,
            target,
            {
                "source_system": "SAM_CONTRACT_AWARDS",
                "award_id": _clean(row.get("piid"), 160) or _clean(row.get("award_id"), 160) or None,
                "piid": _clean(row.get("piid"), 160) or None,
                "modification_number": _clean(row.get("modification_number"), 80) or None,
                "solicitation_id": _clean(row.get("solicitation_id"), 160) or None,
                "recipient_name": _clean(row.get("recipient_name"), 300) or None,
                "recipient_cage": _clean(row.get("recipient_cage"), 20) or None,
                "recipient_uei": _clean(row.get("recipient_uei"), 80) or None,
                "awarding_agency": _clean(row.get("contracting_subtier") or row.get("contracting_department"), 240) or None,
                "contracting_department": _clean(row.get("contracting_department"), 240) or None,
                "contracting_subtier": _clean(row.get("contracting_subtier"), 240) or None,
                "award_date": _clean(row.get("award_date"), 40) or None,
                "award_amount": _to_float(row.get("award_amount")),
                "description": _clean(row.get("description")) or None,
                "psc_code": _clean(row.get("psc"), 20) or target.get("fsc"),
                "naics_code": _clean(row.get("naics"), 20) or None,
                "match_score": score,
                "match_confidence": confidence,
                "match_reasons": reasons,
                "raw_payload": row.get("raw") or row,
            },
        )
        created += int(result == "created")
        updated += int(result == "updated")

    db.flush()
    return summarize_award_history(db, opp.id) | {
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def summarize_award_history(db: Session, opp_id: int) -> dict[str, Any]:
    rows = (
        db.query(AwardHistory)
        .filter(AwardHistory.opportunity_id == opp_id, AwardHistory.match_confidence != "weak")
        .order_by(AwardHistory.match_score.desc().nullslast(), AwardHistory.award_date.desc().nullslast())
        .limit(50)
        .all()
    )
    counts = {"exact": 0, "strong": 0, "broad": 0, "weak": 0}
    source_counts: dict[str, int] = {}
    for row in rows:
        confidence = row.match_confidence or "weak"
        counts[confidence] = counts.get(confidence, 0) + 1
        source_counts[row.source_system] = source_counts.get(row.source_system, 0) + 1
    top_rows = [
        {
            "source_system": row.source_system,
            "award_id": row.award_id,
            "piid": row.piid,
            "recipient_name": row.recipient_name,
            "recipient_cage": row.recipient_cage,
            "award_date": row.award_date,
            "award_amount": row.award_amount,
            "description": row.description,
            "psc_code": row.psc_code,
            "match_score": row.match_score,
            "match_confidence": row.match_confidence,
            "match_reasons": row.match_reasons or [],
        }
        for row in rows[:8]
    ]
    vendor_rollup: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.recipient_name or row.recipient_cage or "Unknown awardee"
        bucket = vendor_rollup.setdefault(
            name,
            {
                "recipient_name": row.recipient_name,
                "recipient_cage": row.recipient_cage,
                "award_count": 0,
                "total_award_amount": 0.0,
                "latest_award_date": "",
                "best_confidence": row.match_confidence,
                "best_score": row.match_score or 0,
                "sources": set(),
            },
        )
        bucket["award_count"] += 1
        if row.award_amount:
            bucket["total_award_amount"] += float(row.award_amount)
        if row.award_date and str(row.award_date) > str(bucket["latest_award_date"] or ""):
            bucket["latest_award_date"] = row.award_date
        if (row.match_score or 0) > (bucket["best_score"] or 0):
            bucket["best_score"] = row.match_score or 0
            bucket["best_confidence"] = row.match_confidence
        bucket["sources"].add(row.source_system)
    top_awardees = sorted(
        vendor_rollup.values(),
        key=lambda item: (item["best_confidence"] != "exact", item["best_confidence"] != "strong", -item["award_count"], -item["total_award_amount"], item["recipient_name"] or ""),
    )[:8]
    for item in top_awardees:
        item["sources"] = sorted(item["sources"])
        item["total_award_amount"] = round(item["total_award_amount"], 2)
    return {
        "stored_count": len(rows),
        "confidence_counts": counts,
        "source_counts": source_counts,
        "top_awards": top_rows,
        "top_awardees": top_awardees,
    }


def _confidence_notes(target: dict[str, Any], research: dict[str, Any], seeded: dict[str, Any], provider_sync: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if target.get("nsn"):
        notes.append("NSN was extracted and normalized for item-level research.")
    if target.get("fsc"):
        notes.append("FSC/PSC was used to constrain historical award searches.")
    if target.get("manufacturer_cages") or target.get("manufacturer_names"):
        notes.append("Approved-source or provider hints were available for supplier matching.")
    if research.get("history_match_source") == "nsn_direct":
        notes.append("USAspending returned direct NSN keyword history.")
    elif research.get("history_match_source") == "fallback":
        notes.append("USAspending matches are based on PSC/FSC and item keywords, not exact NSN.")
    else:
        notes.append("No strong USAspending history match was found yet.")
    if seeded.get("seeded_count"):
        notes.append(f"{seeded.get('seeded_count')} high-confidence awardee/provider leads were linked to the workspace.")
    if provider_sync.get("matched"):
        notes.append(f"{provider_sync.get('matched')} provider records matched this NSN or approved-source CAGE.")
    return notes


def _sam_validation_notes(sam_validation: dict[str, Any]) -> list[str]:
    if not sam_validation.get("enabled"):
        return ["SAM Contract Awards validation is not enabled because the SAM API key is missing."]
    if sam_validation.get("validated_count"):
        return [f"{sam_validation.get('validated_count')} official SAM contract award record(s) matched with validation confidence."]
    if sam_validation.get("records_found"):
        return ["SAM returned contract records, but none met the validation threshold for this NSN/item."]
    if sam_validation.get("errors"):
        return ["SAM Contract Awards validation ran with errors; check query diagnostics."]
    return ["SAM Contract Awards did not return matching official award records yet."]


def run_nsn_intelligence(
    db: Session,
    opp: Opportunity,
    *,
    seed_awardees: bool = True,
    create_summary_artifact: bool = True,
    user_id: int | None = None,
) -> dict[str, Any]:
    parsed = ensure_parsed(db, opp) or {}
    target = build_nsn_research_target(db, opp)
    provider_sync = seed_vendor_leads_from_providers(
        db,
        opp,
        parsed=parsed,
        organization_id=getattr(opp, "organization_id", None),
        user_id=user_id,
    )
    research = search_usaspending_for_opportunity(opp, db=db)
    sam_validation = search_sam_contract_awards_for_target(db, target, limit=25, user_id=user_id)
    award_history = persist_award_history(db, opp, target, research, sam_validation)
    seeded = (
        seed_usaspending_vendors_into_leads(db, opp, research, seed_mode="product_only")
        if seed_awardees
        else {"created": 0, "updated": 0, "seeded_count": 0, "seeded": []}
    )
    vendor_profiles = _vendor_profiles_from_awards(
        research.get("likely_vendors")
        or research.get("seedable_product_like_vendors")
        or research.get("product_like_vendors")
        or []
    )
    pricing = _pricing_summary(db, opp.id)
    summary = {
        "target": target,
        "history": {
            "source": "USAspending",
            "match_source": research.get("history_match_source"),
            "match_label": research.get("history_match_label"),
            "query_label": research.get("history_match_query_label"),
            "awards_found": research.get("awards_found", 0),
            "product_like_awards_found": len(research.get("product_like_awards") or []),
            "likely_vendor_count": len(research.get("likely_vendors") or []),
        },
        "vendor_profiles": vendor_profiles,
        "pricing": pricing,
        "sam_contract_awards": sam_validation,
        "award_history": award_history,
        "provider_sync": provider_sync,
        "awardee_seed": seeded,
        "confidence_notes": _confidence_notes(target, research, seeded, provider_sync) + _sam_validation_notes(sam_validation),
        "generated_at": datetime.utcnow().isoformat(),
    }
    if create_summary_artifact:
        create_artifact(
            db,
            opp.id,
            "RESEARCH_BRIEF",
            f"Research Brief - {opp.solicitation_number or opp.id}",
            content_json={
                "research_profile": target,
                "nsn_intelligence": summary,
                "usaspending_snapshot": {
                    "awards_found": research.get("awards_found", 0),
                    "likely_vendors": (research.get("likely_vendors") or [])[:5],
                    "product_like_vendors": (research.get("product_like_vendors") or [])[:5],
                    "query_debug": (research.get("query_debug") or [])[:5],
                },
                "summary": {
                    "source": opp.source,
                    "agency": opp.agency,
                    "solicitation_number": opp.solicitation_number,
                    "title": getattr(opp, "display_title", None) or opp.title,
                },
            },
            replace_existing=True,
        )
    return summary


def get_nsn_intelligence(db: Session, opp: Opportunity) -> dict[str, Any]:
    artifact = (
        db.query(WorkspaceArtifact)
        .filter(
            WorkspaceArtifact.opportunity_id == opp.id,
            WorkspaceArtifact.artifact_type == "RESEARCH_BRIEF",
        )
        .order_by(WorkspaceArtifact.created_at.desc())
        .first()
    )
    content = dict(getattr(artifact, "content_json", None) or {})
    if content.get("nsn_intelligence"):
        intelligence = dict(content["nsn_intelligence"])
        intelligence.setdefault("award_history", summarize_award_history(db, opp.id))
        return intelligence
    return {
        "target": build_nsn_research_target(db, opp),
        "history": {},
        "vendor_profiles": [],
        "pricing": _pricing_summary(db, opp.id),
        "award_history": summarize_award_history(db, opp.id),
        "provider_sync": {},
        "awardee_seed": {},
        "confidence_notes": ["NSN intelligence has not been run for this opportunity yet."],
        "generated_at": None,
    }
