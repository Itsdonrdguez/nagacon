from __future__ import annotations

import re
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.vendor import VendorLead
from app.repositories.opportunities import OpportunityRepository
from app.repositories.vendor_matches import VendorMatchRepository
from app.schemas.vendor_match import VendorMatchCreate

STOPWORDS = {
    "the","and","for","with","this","that","from","into","shall","will","are",
    "you","your","their","our","have","has","not","all","any","can","may",
    "contract","solicitation","vendor","quote","proposal","response","requirement",
}


def _extract_keywords(title: str | None, description: str | None, max_terms: int = 12) -> List[str]:
    text = f"{title or ''} {description or ''}".lower()
    tokens = re.findall(r"\b[a-z0-9][a-z0-9\-]{2,}\b", text)

    seen = set()
    keywords: List[str] = []

    for token in tokens:
        if token in STOPWORDS or token.isdigit() or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= max_terms:
            break

    return keywords


def _score_vendor(vendor: VendorLead, naics_code: str | None, keywords: List[str], opp_nsn: str | None, opp_fsc: str | None) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []

    haystack = " ".join([
        vendor.company_name or "",
        vendor.notes or "",
        vendor.raw_text or "",
        vendor.cage or "",
        vendor.part_number or "",
        vendor.nsn or "",
    ]).lower()

    if vendor.is_approved_source:
        score += 0.40
        reasons.append("Approved source")

    confidence = int(vendor.confidence or 0)
    if confidence >= 95:
        score += 0.25
        reasons.append("High confidence lead")
    elif confidence >= 80:
        score += 0.15
        reasons.append("Strong confidence lead")
    elif confidence >= 60:
        score += 0.08
        reasons.append("Moderate confidence lead")

    if opp_nsn and vendor.nsn and vendor.nsn.replace("-", "") == opp_nsn.replace("-", ""):
        score += 0.20
        reasons.append("Exact NSN match")

    if opp_fsc and opp_fsc.lower() in haystack:
        score += 0.08
        reasons.append(f"FSC context: {opp_fsc}")

    if naics_code and naics_code.lower() in haystack:
        score += 0.10
        reasons.append(f"NAICS match: {naics_code}")

    kw_hits = sum(1 for kw in keywords if kw in haystack)
    if kw_hits:
        score += min(0.20, kw_hits * 0.05)
        reasons.append(f"Keyword hits: {kw_hits}")

    if vendor.cage:
        score += 0.03
        reasons.append("Has CAGE")
    if vendor.part_number:
        score += 0.04
        reasons.append("Has part number")

    return min(score, 1.0), reasons


def discover_vendors_for_opportunity(opportunity_id: int, db: Session) -> dict:
    repo = OpportunityRepository(db)
    opp = repo.get(opportunity_id)
    if not opp:
        raise ValueError("Opportunity not found")

    keywords = _extract_keywords(opp.title, getattr(opp, "description", None))
    naics_code = getattr(opp, "naics_code", None)
    opp_nsn = None
    raw_payload = getattr(opp, "raw_payload", None) or {}
    dibbs_detail = raw_payload.get("dibbs_detail") or {}
    opp_nsn = dibbs_detail.get("nsn") or raw_payload.get("dibbs_nsn")
    opp_fsc = getattr(opp, "fsc_code", None)

    vendors = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opportunity_id)
        .order_by(VendorLead.company_name.asc())
        .limit(200)
        .all()
    )

    match_repo = VendorMatchRepository(db)
    created_or_updated = 0

    for vendor in vendors:
        score, reasons = _score_vendor(vendor, naics_code, keywords, opp_nsn, opp_fsc)

        if score < 0.20:
            continue

        source = "approved_source" if vendor.is_approved_source else "rule_based"
        payload = VendorMatchCreate(
            vendor_id=vendor.id,
            opportunity_id=opportunity_id,
            match_reason="; ".join(reasons),
            confidence_score=score,
            source=source,
        )
        match_repo.create_or_update(
            vendor_id=payload.vendor_id,
            opportunity_id=payload.opportunity_id,
            match_reason=payload.match_reason,
            confidence_score=payload.confidence_score,
            source=payload.source,
        )
        created_or_updated += 1

    shortlist = match_repo.list_by_opportunity_id(opportunity_id)

    return {
        "opportunity_id": opportunity_id,
        "keywords": keywords,
        "count": len(shortlist),
        "created_or_updated": created_or_updated,
        "matches": shortlist,
    }
