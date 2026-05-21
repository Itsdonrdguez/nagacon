from __future__ import annotations

from typing import Any


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clean_list(values: list[Any] | None) -> list[str]:
    return [str(value).strip() for value in list(values or []) if str(value or "").strip()]


def _contains_any(text: str, candidates: list[str] | None) -> list[str]:
    haystack = text.lower()
    return [candidate for candidate in _clean_list(candidates) if candidate.lower() in haystack]


def _split_text_chunks(value: str | None) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    normalized = text.replace("\r", "\n")
    chunks = [chunk.strip(" -\t") for chunk in normalized.replace(";", "\n").split("\n")]
    return [chunk for chunk in chunks if chunk]


def _build_result(summary: str, signals: list[str], gaps: list[str], matched_fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": summary,
        "signals": signals or ["This opportunity still needs a manual capability review against your profile."],
        "gaps": gaps or ["No major capability gaps were obvious from the current opportunity data."],
        "matched_fields": matched_fields,
    }


def build_sam_capability_match(opp, company_profile) -> dict[str, Any]:
    if not company_profile:
        return _build_result(
            "Add a company profile to compare this opportunity against your capabilities.",
            [],
            ["No company profile is available yet."],
            {},
        )

    title = _clean_text(getattr(opp, "title", None))
    agency = _clean_text(getattr(opp, "agency", None))
    naics = _clean_text(getattr(opp, "naics", None))
    place = _clean_text(getattr(opp, "place_of_performance", None))
    source_text = " ".join(
        part
        for part in [
            title,
            _clean_text(getattr(opp, "raw_text", None)),
            _clean_text((getattr(opp, "parsed_json", None) or {}).get("sam_intelligence", {}).get("summary")),
        ]
        if part
    )

    preferred_naics = _clean_list(getattr(company_profile, "preferred_sam_naics_codes", None) or getattr(company_profile, "naics_codes", None))
    preferred_agencies = _clean_list(getattr(company_profile, "preferred_sam_agencies", None))
    preferred_states = [item.upper() for item in _clean_list(getattr(company_profile, "preferred_sam_states", None))]
    preferred_keywords = _clean_list(getattr(company_profile, "preferred_sam_keywords", None))
    certifications = _clean_list(getattr(company_profile, "certifications", None))
    competencies = _split_text_chunks(getattr(company_profile, "core_competencies", None))
    differentiators = _split_text_chunks(getattr(company_profile, "differentiators", None))
    past_performance = _clean_text(getattr(company_profile, "past_performance_summary", None))

    matched_keywords = _contains_any(source_text, preferred_keywords)
    matched_agencies = _contains_any(agency, preferred_agencies)
    matched_certifications = _contains_any(source_text, certifications)
    matched_competencies = _contains_any(source_text, competencies)
    matched_differentiators = _contains_any(source_text, differentiators)
    geography_match = place and any(state in place.upper() for state in preferred_states)
    naics_match = naics and naics in preferred_naics
    past_performance_match = bool(past_performance and source_text and any(term in source_text.lower() for term in past_performance.lower().split() if len(term) > 4))

    signals: list[str] = []
    gaps: list[str] = []

    if naics_match:
        signals.append(f"NAICS {naics} is already in your company profile.")
    elif naics:
        gaps.append(f"NAICS {naics} is not listed in your saved SAM targeting yet.")

    if matched_agencies:
        signals.append(f"Agency targeting aligns with {agency}.")
    elif agency and preferred_agencies:
        gaps.append(f"{agency} is not one of your preferred agencies yet.")

    if geography_match:
        signals.append("Place of performance lines up with your preferred geography.")
    elif place and preferred_states:
        gaps.append("Place of performance does not line up with your saved target states.")

    if matched_keywords:
        signals.append(f"Opportunity language matches your focus keywords: {', '.join(matched_keywords[:4])}.")
    elif preferred_keywords:
        gaps.append("None of your saved focus keywords appeared clearly in the notice text.")

    if matched_certifications:
        signals.append(f"Solicitation language references certifications you track: {', '.join(matched_certifications[:3])}.")
    elif certifications:
        gaps.append("No saved certifications were referenced directly in the notice text.")

    if matched_competencies:
        signals.append(f"Core competencies line up with the scope: {', '.join(matched_competencies[:3])}.")
    elif competencies:
        gaps.append("Your core competencies are not clearly reflected in the extracted scope yet.")

    if matched_differentiators:
        signals.append(f"Differentiators that may matter here: {', '.join(matched_differentiators[:2])}.")

    if past_performance_match:
        signals.append("Past performance language overlaps with this opportunity.")
    elif past_performance:
        gaps.append("Past performance overlap is not obvious from the current notice text.")

    if not signals:
        signals.append("This opportunity still needs a manual capability review against your profile.")

    if not gaps:
        gaps.append("No major capability gaps were obvious from the current notice text.")

    headline_parts = []
    if naics_match:
        headline_parts.append("NAICS alignment is present")
    if matched_keywords or matched_competencies:
        headline_parts.append("scope language overlaps with your profile")
    if matched_agencies:
        headline_parts.append("agency targeting matches")
    if geography_match:
        headline_parts.append("geography fits")

    if headline_parts:
        summary = "Capability match looks promising: " + "; ".join(headline_parts) + "."
    else:
        summary = "Capability match is still inconclusive from the saved profile and current notice text."

    return _build_result(
        summary,
        signals,
        gaps,
        {
            "naics": naics if naics_match else "",
            "agencies": matched_agencies,
            "keywords": matched_keywords,
            "certifications": matched_certifications,
            "competencies": matched_competencies,
            "differentiators": matched_differentiators,
            "geography": bool(geography_match),
            "past_performance": bool(past_performance_match),
        },
    )


def build_product_capability_match(opp, company_profile) -> dict[str, Any]:
    if not company_profile:
        return _build_result(
            "Add a company profile to compare this opportunity against your product capabilities.",
            [],
            ["No company profile is available yet."],
            {},
        )

    title = _clean_text(getattr(opp, "title", None))
    fsc = _clean_text(getattr(opp, "fsc", None))
    raw_text = _clean_text(getattr(opp, "raw_text", None))
    parsed_json = getattr(opp, "parsed_json", None) or {}
    item_description = _clean_text(parsed_json.get("item_description") or parsed_json.get("nomenclature"))
    source_text = " ".join(part for part in [title, item_description, raw_text] if part)

    preferred_fscs = _clean_list(getattr(company_profile, "preferred_dibbs_fsc_codes", None))
    preferred_keywords = _clean_list(getattr(company_profile, "preferred_sam_keywords", None))
    certifications = _clean_list(getattr(company_profile, "certifications", None))
    competencies = _split_text_chunks(getattr(company_profile, "core_competencies", None))
    differentiators = _split_text_chunks(getattr(company_profile, "differentiators", None))

    fsc_match = bool(fsc and fsc in preferred_fscs)
    matched_keywords = _contains_any(source_text, preferred_keywords)
    matched_competencies = _contains_any(source_text, competencies)
    matched_differentiators = _contains_any(source_text, differentiators)
    matched_certifications = _contains_any(source_text, certifications)

    signals: list[str] = []
    gaps: list[str] = []

    if fsc_match:
        signals.append(f"FSC {fsc} is already in your preferred DIBBS targeting.")
    elif fsc:
        gaps.append(f"FSC {fsc} is not listed in your saved DIBBS targeting yet.")

    if matched_keywords:
        signals.append(f"Item language matches your focus keywords: {', '.join(matched_keywords[:4])}.")
    elif preferred_keywords:
        gaps.append("None of your saved focus keywords appeared clearly in the current product description.")

    if matched_competencies:
        signals.append(f"Core competencies line up with the product scope: {', '.join(matched_competencies[:3])}.")
    elif competencies:
        gaps.append("Your core competencies are not clearly reflected in the current product description yet.")

    if matched_certifications:
        signals.append(f"Saved certifications appear relevant here: {', '.join(matched_certifications[:3])}.")

    if matched_differentiators:
        signals.append(f"Differentiators that may help here: {', '.join(matched_differentiators[:2])}.")

    if fsc_match or matched_keywords or matched_competencies:
        summary = "Capability match looks promising for this product opportunity."
    else:
        summary = "Capability match is still inconclusive from the saved profile and current product details."

    return _build_result(
        summary,
        signals,
        gaps,
        {
            "fsc": fsc if fsc_match else "",
            "keywords": matched_keywords,
            "certifications": matched_certifications,
            "competencies": matched_competencies,
            "differentiators": matched_differentiators,
        },
    )


def build_capability_match(opp, company_profile) -> dict[str, Any]:
    source = _clean_text(getattr(opp, "source", None)).upper()
    if source == "SAM":
        return build_sam_capability_match(opp, company_profile)
    return build_product_capability_match(opp, company_profile)
