from __future__ import annotations

import re


SET_ASIDE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b8\s*\(?a\)?\b", re.I), "EIGHT_A"),
    (re.compile(r"\bedwosb\b|economically disadvantaged women", re.I), "EDWOSB"),
    (re.compile(r"\bwosb\b|women-owned", re.I), "WOSB"),
    (re.compile(r"\bhub\s*zone\b|\bhubzone\b", re.I), "HUBZONE"),
    (re.compile(r"\bsdvosb\b|service[-\s]*disabled veteran", re.I), "SDVOSB"),
    (re.compile(r"\bvosb\b|veteran[-\s]*owned", re.I), "VOSB"),
    (re.compile(r"\bsmall[-_\s]*business\b|\btotal small\b|\bsbsa\b", re.I), "SMALL_BUSINESS"),
    (re.compile(r"\bcombined\b", re.I), "COMBINED"),
    (re.compile(r"\bunrestricted\b|\bfull and open\b|\bnot set aside\b", re.I), "UNRESTRICTED"),
]

SET_ASIDE_LABELS: dict[str, str] = {
    "EIGHT_A": "8(a)",
    "EDWOSB": "EDWOSB",
    "WOSB": "WOSB",
    "HUBZONE": "HUBZone",
    "SDVOSB": "SDVOSB",
    "VOSB": "Veteran-Owned",
    "SMALL_BUSINESS": "Small Business",
    "COMBINED": "Combined Set-Aside",
    "UNRESTRICTED": "Full and Open",
}


def normalize_set_aside(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
      return None
    canonical = text.upper().replace(" ", "_").replace("-", "_")
    if canonical in SET_ASIDE_LABELS:
        return canonical
    for pattern, label in SET_ASIDE_PATTERNS:
        if pattern.search(text):
            return label
    return re.sub(r"\s+", " ", text).strip()


def set_aside_display_label(value: str | None) -> str | None:
    normalized = normalize_set_aside(value)
    if not normalized:
        return None
    if normalized in SET_ASIDE_LABELS:
        return SET_ASIDE_LABELS[normalized]
    return normalized.replace("_", " ").title()
