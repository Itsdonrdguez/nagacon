from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.models.opportunity import Opportunity, OpportunityAnalysis


_REQUIREMENT_KEYWORDS = (
    "shall",
    "must",
    "provide",
    "submit",
    "include",
    "furnish",
    "deliver",
    "capability statement",
    "past performance",
    "technical",
    "quote",
    "proposal",
)

_RISK_PHRASES = {
    "site visit": "Site visit requirement mentioned.",
    "mandatory": "Mandatory participation language found.",
    "security clearance": "Security clearance requirement mentioned.",
    "brand name": "Brand-name or restrictive language detected.",
    "experience": "Experience or qualification requirement mentioned.",
}


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _sentence_split(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [_clean_text(part) for part in parts if _clean_text(part)]


def _extract_resource_links(payload: dict[str, Any]) -> list[str]:
    links: list[str] = []
    for key in ("resourceLinks", "attachments", "attachmentLinks", "fileLinks"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    link = _clean_text(item.get("url") or item.get("href") or item.get("link"))
                    if link:
                        links.append(link)
                else:
                    link = _clean_text(item)
                    if link:
                        links.append(link)
    seen: set[str] = set()
    deduped: list[str] = []
    for item in links:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _extract_requirements(text: str) -> list[str]:
    requirements: list[str] = []
    for sentence in _sentence_split(text):
        lower = sentence.lower()
        if any(keyword in lower for keyword in _REQUIREMENT_KEYWORDS):
            requirements.append(sentence)
    seen: set[str] = set()
    deduped: list[str] = []
    for item in requirements:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]


def _normalize_comparable_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _days_until_due(due_at: datetime | None) -> int | None:
    due_value = _normalize_comparable_datetime(due_at)
    if due_value is None:
        return None
    current_time = datetime.now(timezone.utc)
    return int((due_value - current_time).total_seconds() // 86400)


def _build_summary(
    *,
    title: str | None,
    agency: str | None,
    due_at: datetime | None,
    naics: str | None,
    set_aside: str | None,
    place_of_performance: str | None,
    description: str,
) -> str | None:
    lead = _clean_text(title) or "This opportunity"
    opening = lead if lead.endswith(".") else f"{lead}."
    summary_parts = [opening]

    desc_sentence = next(iter(_sentence_split(description)), "")
    if desc_sentence:
        summary_parts.append(desc_sentence if desc_sentence.endswith(".") else f"{desc_sentence}.")

    facts: list[str] = []
    if agency:
        facts.append(f"Agency: {_clean_text(agency)}")
    if due_at:
        facts.append(f"Due: {due_at.strftime('%b %d, %Y').replace(' 0', ' ') if hasattr(due_at, 'strftime') else due_at}")
    if naics:
        facts.append(f"NAICS: {_clean_text(naics)}")
    if set_aside:
        facts.append(f"Set-aside: {_clean_text(set_aside)}")
    if place_of_performance:
        facts.append(f"Place of performance: {_clean_text(place_of_performance)}")
    if facts:
        summary_parts.append(" ".join(facts) + ".")

    summary = " ".join(part for part in summary_parts if part)
    return summary[:900] if summary else None


def build_sam_opportunity_intelligence(opp: Opportunity) -> dict[str, Any]:
    payload = dict(getattr(opp, "raw_payload", None) or {})
    description = _clean_text(getattr(opp, "raw_text", None) or "")
    resource_links = _extract_resource_links(payload)
    requirements = _extract_requirements(description)

    risk_flags: list[str] = []
    days_until_due = _days_until_due(getattr(opp, "due_at", None))
    if days_until_due is not None:
        if days_until_due <= 3:
            risk_flags.append("Response window is extremely short.")
        elif days_until_due <= 7:
            risk_flags.append("Response window closes within one week.")
    if not description:
        risk_flags.append("SAM notice does not include a usable description.")
    if not requirements and description:
        risk_flags.append("No clear submission requirements were extracted from the notice text.")
    if not resource_links:
        risk_flags.append("No attachment or resource links were surfaced from the SAM payload.")

    lower_description = description.lower()
    for phrase, message in _RISK_PHRASES.items():
        if phrase in lower_description:
            risk_flags.append(message)

    seen_risks: set[str] = set()
    deduped_risks: list[str] = []
    for item in risk_flags:
        if item in seen_risks:
            continue
        seen_risks.add(item)
        deduped_risks.append(item)

    summary = _build_summary(
        title=getattr(opp, "title", None),
        agency=getattr(opp, "agency", None),
        due_at=getattr(opp, "due_at", None),
        naics=getattr(opp, "naics_code", None),
        set_aside=getattr(opp, "set_aside_type", None),
        place_of_performance=getattr(opp, "place_of_performance", None),
        description=description,
    )

    return {
        "summary": summary,
        "requirements": requirements,
        "risk_flags": deduped_risks,
        "resource_links": resource_links,
        "resource_link_count": len(resource_links),
    }


def apply_sam_opportunity_intelligence(opp: Opportunity) -> OpportunityAnalysis:
    intelligence = build_sam_opportunity_intelligence(opp)

    parsed_json = dict(getattr(opp, "parsed_json", None) or {})
    parsed_json["sam_intelligence"] = intelligence
    parsed_json["requirements"] = intelligence.get("requirements") or []
    parsed_json["risk_flags"] = intelligence.get("risk_flags") or []
    opp.parsed_json = parsed_json

    analysis = getattr(opp, "analysis", None)
    if analysis is None:
        analysis = OpportunityAnalysis(
            opportunity=opp,
            fit_score=0,
            priority_score=getattr(getattr(opp, "analysis", None), "priority_score", 0) or 0,
            risk_flags=intelligence.get("risk_flags") or [],
            ai_summary=intelligence.get("summary"),
        )
    else:
        analysis.risk_flags = intelligence.get("risk_flags") or []
        analysis.ai_summary = intelligence.get("summary")
    return analysis
