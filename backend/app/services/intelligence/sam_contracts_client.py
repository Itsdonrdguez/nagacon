from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.services.provider_settings_service import get_effective_sam_api_key

SAM_CONTRACT_AWARDS_URL = "https://api.sam.gov/contract-awards/v1/search"
HTTP_TIMEOUT = 45


def _clean(value: Any, max_len: int | None = None) -> str:
    text = "" if value is None else re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return ""
    return text[:max_len] if max_len else text


def _walk_values(node: Any, wanted_keys: set[str]) -> str:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted_keys and value not in (None, ""):
                return _clean(value)
        for value in node.values():
            found = _walk_values(value, wanted_keys)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_values(item, wanted_keys)
            if found:
                return found
    return ""


def _walk_number(node: Any, wanted_keys: set[str]) -> float | None:
    value = _walk_values(node, wanted_keys)
    if not value:
        return None
    try:
        return float(value.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def _first_path_value(node: dict[str, Any], paths: list[tuple[str, ...]]) -> str:
    for path in paths:
        value = _path(node, *path)
        if value not in (None, ""):
            return _clean(value)
    return ""


def _first_path_number(node: dict[str, Any], paths: list[tuple[str, ...]]) -> float | None:
    for path in paths:
        value = _path(node, *path)
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(",", "").replace("$", ""))
        except ValueError:
            continue
    return None


def _path(node: dict[str, Any], *parts: str) -> Any:
    current: Any = node
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _date_range_years(years: int = 8) -> str:
    start = (datetime.utcnow() - timedelta(days=365 * years)).strftime("%m/%d/%Y")
    end = datetime.utcnow().strftime("%m/%d/%Y")
    return f"[{start},{end}]"


def _keyword_query(values: list[str], limit: int = 4) -> str:
    terms = []
    for value in values:
        text = _clean(value)
        if not text or text.isdigit():
            continue
        if re.match(r"^\d{4}-?\d{2}-?\d{3}-?\d{4}$", text):
            terms.append(text)
            continue
        if len(text) >= 3:
            terms.append(text)
        if len(terms) >= limit:
            break
    return " ".join(terms)


def _build_query_plans(target: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base = {
        "limit": str(max(1, min(limit, 100))),
        "offset": "0",
        "approvedDate": _date_range_years(8),
        "includeSections": "contractId,coreData,awardDetails,awardeeData",
    }
    fsc = _clean(target.get("fsc"))
    keywords = [str(x) for x in target.get("keywords") or []]
    part_numbers = [str(x) for x in target.get("part_numbers") or []]
    manufacturers = [str(x) for x in target.get("manufacturer_names") or []]
    nsn = _clean(target.get("nsn") or target.get("nsn_compact"))
    plans: list[dict[str, Any]] = []

    def add(label: str, params: dict[str, Any]) -> None:
        clean_params = {k: v for k, v in params.items() if v not in (None, "")}
        plans.append({"label": label, "params": clean_params})

    if nsn:
        add("sam_nsn_keyword", {**base, "q": nsn})
    if fsc:
        add("sam_psc_keywords", {**base, "productOrServiceCode": fsc, "q": _keyword_query(keywords, 5), "contractingDepartmentCode": "9700"})
        add("sam_psc_purchase_orders", {**base, "productOrServiceCode": fsc, "awardOrIDVTypeName": "PURCHASE ORDER", "contractingDepartmentCode": "9700"})
    for part in part_numbers[:3]:
        add("sam_part_number", {**base, "productOrServiceCode": fsc, "q": part, "contractingDepartmentCode": "9700"})
    for manufacturer in manufacturers[:3]:
        add("sam_manufacturer", {**base, "productOrServiceCode": fsc, "q": manufacturer, "contractingDepartmentCode": "9700"})

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for plan in plans:
        key = repr(sorted(plan["params"].items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(plan)
    return deduped[:8]


def _score_sam_award(row: dict[str, Any], target: dict[str, Any]) -> tuple[float, list[str]]:
    text = " ".join(
        [
            row.get("piid") or "",
            row.get("solicitation_id") or "",
            row.get("recipient_name") or "",
            row.get("description") or "",
            row.get("psc") or "",
            row.get("contracting_department") or "",
            row.get("contracting_subtier") or "",
        ]
    ).upper()
    score = 0.0
    reasons: list[str] = []
    nsn = _clean(target.get("nsn")).upper()
    compact_nsn = _clean(target.get("nsn_compact")).upper()
    if nsn and nsn in text:
        score += 35
        reasons.append("NSN found in official contract record text.")
    if compact_nsn and compact_nsn in text:
        score += 30
        reasons.append("Compact NSN found in official contract record text.")
    if target.get("fsc") and str(row.get("psc") or "").startswith(str(target["fsc"])):
        score += 20
        reasons.append("PSC/FSC matches the DIBBS item class.")
    for part in target.get("part_numbers") or []:
        if part and str(part).upper() in text:
            score += 25
            reasons.append(f"Part number matched: {part}.")
            break
    for manufacturer in target.get("manufacturer_names") or []:
        if manufacturer and str(manufacturer).upper() in text:
            score += 20
            reasons.append(f"Manufacturer/provider hint matched: {manufacturer}.")
            break
    keyword_hits = 0
    for keyword in target.get("keywords") or []:
        kw = str(keyword).upper()
        if len(kw) >= 4 and kw in text:
            keyword_hits += 1
    if keyword_hits:
        score += min(15, keyword_hits * 3)
        reasons.append(f"{keyword_hits} item keyword(s) matched.")
    if "DEFENSE" in text or "DLA" in text:
        score += 5
        reasons.append("Defense/DLA contract context.")
    return round(min(score, 100), 2), reasons[:6]


def _normalize_award(row: dict[str, Any], label: str, target: dict[str, Any]) -> dict[str, Any]:
    contract_id = row.get("contractId") if isinstance(row.get("contractId"), dict) else {}
    core = row.get("coreData") if isinstance(row.get("coreData"), dict) else {}
    award_details = row.get("awardDetails") if isinstance(row.get("awardDetails"), dict) else {}
    product_service = _path(core, "productOrServiceInformation", "productOrService") or {}
    principal_naics = _path(core, "productOrServiceInformation", "principalNaics")
    if isinstance(principal_naics, list) and principal_naics:
        principal_naics = principal_naics[0]
    elif not isinstance(principal_naics, dict):
        principal_naics = {}
    contracting_info = _path(core, "federalOrganization", "contractingInformation") or {}
    contracting_department = _path(contracting_info, "contractingDepartment") or {}
    contracting_subtier = _path(contracting_info, "contractingSubtier") or {}
    awardee_data = _path(award_details, "awardeeData") or {}
    awardee_header = _path(awardee_data, "awardeeHeader") or {}
    awardee_uei = _path(awardee_data, "awardeeUEIInformation") or {}
    dollar_values = _path(core, "dollarValues") or {}
    award_date = (
        _first_path_value(
            core,
            [
                ("dates", "dateSigned"),
                ("dates", "signedDate"),
                ("dates", "approvedDate"),
                ("dateSigned",),
                ("signedDate",),
                ("approvedDate",),
                ("periodOfPerformance", "startDate"),
            ],
        )
        or _walk_values(core, {"approvedDate", "signedDate", "dateSigned", "effectiveDate"})
        or _walk_values(row, {"approvedDate", "signedDate", "dateSigned", "effectiveDate"})
    )
    award_amount = (
        _first_path_number(
            core,
            [
                ("dollarValues", "totalObligatedAmount"),
                ("dollarValues", "obligatedAmount"),
                ("dollarValues", "baseAndExercisedOptionsValue"),
                ("dollarValues", "baseAndAllOptionsValue"),
                ("dollarValues", "currentTotalValueOfAward"),
                ("dollarValues", "potentialTotalValueOfAward"),
            ],
        )
        or _walk_number(
            dollar_values,
            {
                "totalObligatedAmount",
                "obligatedAmount",
                "baseAndExercisedOptionsValue",
                "baseAndAllOptionsValue",
                "currentTotalValueOfAward",
                "potentialTotalValueOfAward",
            },
        )
        or _walk_number(
            row,
            {
                "actionObligation",
                "obligatedAmount",
                "totalObligatedAmount",
                "baseAndExercisedOptionsValue",
                "baseAndAllOptionsValue",
                "currentTotalValueOfAward",
                "potentialTotalValueOfAward",
            },
        )
    )
    score_row = {
        "piid": _walk_values(contract_id, {"piid"}),
        "modification_number": _walk_values(contract_id, {"modificationNumber"}),
        "solicitation_id": _walk_values(core, {"solicitationId"}),
        "recipient_name": _clean(awardee_header.get("awardeeName") or awardee_header.get("awardeeNameFromContract")),
        "recipient_cage": _clean(awardee_uei.get("cageCode")),
        "recipient_uei": _clean(awardee_uei.get("uniqueEntityId")),
        "contracting_department": _clean(contracting_department.get("name")),
        "contracting_subtier": _clean(contracting_subtier.get("name")),
        "psc": _clean(product_service.get("code")),
        "psc_description": _clean(product_service.get("name")),
        "naics": _clean(principal_naics.get("code")),
        "award_type": _walk_values(core, {"awardOrIDVType", "awardOrIDV"}),
        "award_date": award_date,
        "award_amount": award_amount,
        "description": _walk_values(core, {"descriptionOfRequirement", "description"}) or _clean(product_service.get("name")),
        "matched_by": label,
    }
    score, reasons = _score_sam_award(score_row, target)
    score_row["match_score"] = score
    score_row["match_reasons"] = reasons
    score_row["raw"] = row
    return score_row


def search_sam_contract_awards_for_target(db: Session, target: dict[str, Any], *, limit: int = 25) -> dict[str, Any]:
    api_key = get_effective_sam_api_key(db)
    if not api_key:
        return {
            "enabled": False,
            "records_found": 0,
            "validated_records": [],
            "query_debug": [],
            "errors": ["SAM API key is not configured."],
        }
    session = requests.Session()
    session.trust_env = False
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    query_debug: list[dict[str, Any]] = []
    for plan in _build_query_plans(target, limit):
        params = {**plan["params"], "api_key": api_key}
        try:
            response = session.get(SAM_CONTRACT_AWARDS_URL, params=params, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("awardSummary") or []
            query_debug.append({
                "label": plan["label"],
                "count": len(rows),
                "total_records": payload.get("totalRecords"),
                "params": {k: ("***" if k == "api_key" else v) for k, v in params.items()},
            })
            records.extend(_normalize_award(row, plan["label"], target) for row in rows)
        except Exception as exc:
            errors.append(f"{plan['label']}: {exc.__class__.__name__}: {str(exc)[:220]}")

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in sorted(records, key=lambda item: (-float(item.get("match_score") or 0), item.get("piid") or "")):
        key = (record.get("piid") or "", record.get("modification_number") or "", record.get("recipient_name") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)

    candidates = [record for record in deduped if float(record.get("match_score") or 0) >= 30]
    validated = [record for record in deduped if float(record.get("match_score") or 0) >= 45]
    return {
        "enabled": True,
        "raw_records_returned": len(deduped),
        "records_found": len(candidates),
        "validated_count": len(validated),
        "validated_records": validated[:10],
        "top_records": candidates[:10],
        "query_debug": query_debug,
        "errors": errors[:10],
    }
