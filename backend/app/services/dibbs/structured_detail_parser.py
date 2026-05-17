from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


SET_ASIDE_ICON_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"iconedwosb", re.I), "EDWOSB"),
    (re.compile(r"iconwosb", re.I), "WOSB"),
    (re.compile(r"iconhubzone", re.I), "HUBZONE"),
    (re.compile(r"iconsdvosb", re.I), "SDVOSB"),
    (re.compile(r"iconsb", re.I), "SMALL_BUSINESS"),
    (re.compile(r"iconcombined", re.I), "COMBINED"),
    (re.compile(r"iconunrestrictednotsetaside", re.I), "UNRESTRICTED"),
]


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm(text: str | None) -> str | None:
    text = _safe(text)
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()


def extract_full_nsn(blob: str | None) -> str | None:
    if not blob:
        return None

    patterns = [
        r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b",
        r"\bNSN[:\s]+(\d{4}-\d{2}-\d{3}-\d{4})\b",
        r"\b(\d{13})\b",
    ]
    for pat in patterns:
        m = re.search(pat, blob, flags=re.I)
        if m:
            val = m.group(1)
            if len(val) == 13 and val.isdigit():
                return f"{val[:4]}-{val[4:6]}-{val[6:9]}-{val[9:]}"
            return val
    return None


def derive_fsc_from_nsn(nsn: str | None) -> str | None:
    nsn = _safe(nsn)
    if not nsn:
        return None
    m = re.match(r"^(\d{4})-", nsn)
    if m:
        return m.group(1)
    if len(nsn) >= 4 and nsn[:4].isdigit():
        return nsn[:4]
    return None


def collect_file_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        text = _norm(a.get_text(" ", strip=True)) or ""
        key = (href, text)
        if key in seen:
            continue
        seen.add(key)

        if any(tok in href.lower() for tok in [".pdf", "/downloads/", "attachment", "file"]) or "pdf" in text.lower():
            if text.lower() == "downloads":
                continue
            links.append({"text": text, "url": href})

    return links[:100]


def _clean_nomenclature(value: str | None) -> str | None:
    value = _norm(value)
    if not value:
        return None
    value = re.sub(r"\s*AMSC\s*$", "", value, flags=re.I)
    return _norm(value)


def extract_dibbs_set_aside_type_from_strings(values: list[str | None]) -> str | None:
    markers = [value for value in (_norm(item) for item in values) if value]
    if not markers:
        return None
    haystack = " ".join(markers)
    for pattern, label in SET_ASIDE_ICON_MAP:
        if pattern.search(haystack):
            return label
    text_map = [
        (re.compile(r"\b8\(a\)\b", re.I), "8A"),
        (re.compile(r"\bedwosb\b", re.I), "EDWOSB"),
        (re.compile(r"\bwosb\b", re.I), "WOSB"),
        (re.compile(r"\bhubzone\b", re.I), "HUBZONE"),
        (re.compile(r"\bsdvosb\b", re.I), "SDVOSB"),
        (re.compile(r"\bsmall business\b", re.I), "SMALL_BUSINESS"),
        (re.compile(r"\bcombined\b", re.I), "COMBINED"),
        (re.compile(r"\bunrestricted\b", re.I), "UNRESTRICTED"),
        (re.compile(r"\bnot set aside\b", re.I), "UNRESTRICTED"),
    ]
    for pattern, label in text_map:
        if pattern.search(haystack):
            return label
    return None


def extract_dibbs_set_aside_type_from_node(node: Any) -> str | None:
    if node is None:
        return None
    values: list[str | None] = []
    for image in getattr(node, "find_all", lambda *args, **kwargs: [])("img"):
        values.extend([
            image.get("src"),
            image.get("alt"),
            image.get("title"),
        ])
    values.append(getattr(node, "get_text", lambda *args, **kwargs: "")(" ", strip=True))
    return extract_dibbs_set_aside_type_from_strings(values)


def extract_dibbs_set_aside_type_from_html(html: str) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return extract_dibbs_set_aside_type_from_node(soup)


def parse_approved_source_rows(page_text: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    m = re.search(
        r"Approved Source Data\s+CAGE\s+Part Number\s+Company Name\s+(.*?)(?:Solicitations\s+Solicitation #|Policy Statements|Feedback|$)",
        page_text,
        flags=re.I | re.S,
    )
    if not m:
        return results

    section = _norm(m.group(1)) or ""
    if not section:
        return results

    tokens = section.split()
    if len(tokens) >= 3 and re.fullmatch(r"[A-Z0-9]{5}", tokens[0]):
        cage = tokens[0]
        part_number = tokens[1]
        company_name = " ".join(tokens[2:])
        results.append(
            {
                "cage": cage,
                "part_number": part_number,
                "company_name": company_name,
            }
        )

    return results[:50]


def parse_solicitation_rows(page_text: str, base_url: str) -> list[dict[str, str | None]]:
    results: list[dict[str, str | None]] = []
    m = re.search(
        r"Solicitations\s+Solicitation #\s+Technical Documents\s+PR #\s+QTY\s+Issue\s+Return By\s+(.*?)(?:Policy Statements|Feedback|$)",
        page_text,
        flags=re.I | re.S,
    )
    if not m:
        return results

    section = _norm(m.group(1)) or ""
    row_pat = re.compile(
        r"\b([A-Z0-9]{8,})\s+(None|[A-Z0-9]+)\s+(\d{10})\s+(\d+)\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})"
    )
    for mm in row_pat.finditer(section):
        sol, tech_docs, pr_number, qty, issue, ret = mm.groups()
        pdf_url = None
        if sol.upper().startswith("SPE"):
            pdf_url = f"https://dibbs2.bsm.dla.mil/Downloads/RFQ/{sol[-1]}/{sol}.PDF"
        results.append(
            {
                "solicitation_number": sol,
                "technical_documents": tech_docs,
                "pr_number": pr_number,
                "qty": qty,
                "issue_date": issue,
                "return_by_date": ret,
                "pdf_url": pdf_url,
            }
        )

    return results[:100]


def parse_dibbs_detail_structured(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = _norm(soup.get_text(" ", strip=True)) or ""

    title = None
    h1 = soup.find(["h1", "h2", "title"])
    if h1:
        title = _norm(h1.get_text(" ", strip=True))

    nsn = extract_full_nsn(page_text) or extract_full_nsn(url)
    fsc_code = derive_fsc_from_nsn(nsn)

    nomenclature = None
    nm = re.search(
        r"\bNomenclature:\s*(.+?)(?=\s+AMSC:|\s+Approved Source Data|\s+Solicitations\b|$)",
        page_text,
        flags=re.I,
    )
    if nm:
        nomenclature = _clean_nomenclature(nm.group(1))

    amsc = None
    am = re.search(r"\bAMSC:\s*([A-Z0-9]+)", page_text, flags=re.I)
    if am:
        amsc = _norm(am.group(1))

    approved_sources = parse_approved_source_rows(page_text)
    solicitation_rows = parse_solicitation_rows(page_text, url)
    file_links = collect_file_links(soup, url)
    set_aside_type = extract_dibbs_set_aside_type_from_node(soup)

    existing_urls = {x["url"] for x in file_links}
    for row in solicitation_rows:
        pdf_url = row.get("pdf_url")
        sol = row.get("solicitation_number") or ""
        if pdf_url and pdf_url not in existing_urls:
            file_links.append({"text": sol, "url": pdf_url})
            existing_urls.add(pdf_url)

    return {
        "detail_title": title,
        "nsn": nsn,
        "fsc_code": fsc_code,
        "nomenclature": nomenclature,
        "amsc": amsc,
        "set_aside_type": set_aside_type,
        "approved_sources": approved_sources,
        "solicitations": solicitation_rows,
        "file_links": file_links[:100],
        "page_excerpt": page_text[:4000],
    }
