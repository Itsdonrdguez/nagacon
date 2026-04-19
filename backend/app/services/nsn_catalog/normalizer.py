from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedNsn:
    nsn: str
    compact: str
    fsc: str
    niin: str


def compact_nsn(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def format_nsn(value: str | None) -> str:
    digits = compact_nsn(value)
    if len(digits) != 13:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:]}"


def normalize_nsn(value: str | None) -> NormalizedNsn | None:
    digits = compact_nsn(value)
    if len(digits) != 13:
        return None
    return NormalizedNsn(
        nsn=format_nsn(digits),
        compact=digits,
        fsc=digits[:4],
        niin=digits[4:],
    )


def normalize_cage(value: str | None) -> str:
    text = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
    return text[:5] if len(text) >= 5 else text


def clean_part_number(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()
