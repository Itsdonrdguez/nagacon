from __future__ import annotations

import re
import json
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.opportunity_file import OpportunityFile
from app.models.price_history import PriceHistory
from app.repositories.providers import ProviderRepository
from app.schemas.provider import ProviderCreate, ProviderItemCreate
from app.services.provider_settings_service import get_effective_openai_api_key, get_effective_openai_model
from app.services.providers.pdf_cage_extractor import _lookup_sam_entity
from app.services.storage import local_temp_path


PRICE_SECTION_PATTERN = re.compile(
    r"(previous\s+award|prior\s+award|last\s+award|contract\s+history|purchase\s+history|unit\s+price|award\s+price|award\s+amount)",
    re.IGNORECASE,
)
MONEY_PATTERN = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,4}))?")
DOLLAR_PATTERN = re.compile(r"\$\s*(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,4})?")
CAGE_PATTERN = re.compile(r"\b(?=[0-9A-Z]*\d)[0-9A-Z]{5}\b")
DATE_PATTERN = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b")
AWARD_PATTERN = re.compile(r"\b(?:SPE|SPM|W\d|N\d|FA\d|GS[A-Z0-9])[A-Z0-9\-]{5,}\b", re.IGNORECASE)
NSN_PATTERN = re.compile(r"\b(\d{4})[- ]?(\d{2})[- ]?(\d{3})[- ]?(\d{4})\b")
BAD_SUPPLIER_TEXT_PATTERN = re.compile(
    r"(ansi\s+x12|unit\s+of\s+issue|officeapps|view\.officeapps|https?://|www\.dla\.mil|corresponding\s+ansi|portals%)",
    re.IGNORECASE,
)
COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b(?:INC|INCORPORATED|LLC|L\.L\.C|LTD|LIMITED|CORP|CORPORATION|CO\.?|COMPANY|MFG|MANUFACTURING|GROUP|SUPPLY|DENTAL|MEDICAL)\b",
    re.IGNORECASE,
)


def _clean(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text:
        return None
    return text[:max_len] if max_len else text


def _money(value: str | None) -> float | None:
    if not value:
        return None
    match = MONEY_PATTERN.search(value)
    if not match:
        return None
    text = match.group(0).replace("$", "").replace(",", "").replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return None


def _number_near(label_patterns: list[str], text: str) -> float | None:
    for label in label_patterns:
        match = re.search(rf"{label}\s*[:#-]?\s*([0-9,]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _normalize_nsn(value: str | None) -> str | None:
    if not value:
        return None
    match = NSN_PATTERN.search(value)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}-{match.group(4)}"


def _extract_text_with_pdfplumber(path: str | None) -> str:
    if not path:
        return ""
    try:
        import pdfplumber

        pages: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                if text.strip():
                    pages.append(text)
                try:
                    for table in page.extract_tables() or []:
                        lines = [" | ".join(str(cell or "").strip() for cell in row) for row in table if row]
                        pages.extend(lines)
                except Exception:
                    pass
        return "\n".join(pages).strip()
    except Exception:
        return ""


def _candidate_blocks(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if PRICE_SECTION_PATTERN.search(line):
            start = max(0, index - 3)
            end = min(len(lines), index + 10)
            blocks.append(" ".join(lines[start:end]))
    # Table/text rows with both money and vendor-ish identifiers are useful even
    # when the document does not label them as previous-award sections.
    for line in lines:
        if DOLLAR_PATTERN.search(line) and (CAGE_PATTERN.search(line) or AWARD_PATTERN.search(line)):
            blocks.append(line)
    seen = set()
    out = []
    for block in blocks:
        key = block.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(block[:1800])
    return out[:30]


def _supplier_before_cage(block: str, cage: str | None) -> str | None:
    if not cage or cage not in block:
        return None
    before = block.split(cage, 1)[0]
    tokens = before.split()
    if len(tokens) < 2:
        return None
    name = " ".join(tokens[-8:])
    name = re.sub(r"^(AWARD|CONTRACT|PRICE|SUPPLIER|VENDOR)\s+", "", name, flags=re.IGNORECASE)
    if re.search(r"\$|\d{4}-\d{2}", name):
        return None
    if not _looks_like_supplier_name(name):
        return None
    return _clean(name, 240)


def _looks_like_supplier_name(value: str | None) -> bool:
    text = _clean(value, 240)
    if not text:
        return False
    if BAD_SUPPLIER_TEXT_PATTERN.search(text):
        return False
    if len(text) < 4 or len(text) > 120:
        return False
    if text.count("/") >= 2 or text.count("%") >= 1:
        return False
    if re.search(r"\b(unit|issue|corresponding|reference|clause|table|column|portal|download|attachment)\b", text, re.IGNORECASE):
        return False
    letters = len(re.findall(r"[A-Za-z]", text))
    if letters < 3:
        return False
    return bool(COMPANY_SUFFIX_PATTERN.search(text) or "," in text or text.isupper())


def _sam_supplier_for_cage(db: Session, cage: str | None) -> tuple[str | None, str | None]:
    if not cage:
        return None, None
    from app.services.provider_settings_service import get_effective_sam_api_key

    api_key = get_effective_sam_api_key(db)
    if not api_key:
        return None, None
    row = _lookup_sam_entity(cage, api_key)
    if row.get("error"):
        return None, None
    return _clean(row.get("company_name"), 240), _clean(row.get("website"), 500)


def _parse_block(block: str, fallback_nsn: str | None) -> dict[str, Any] | None:
    has_price_context = bool(
        DOLLAR_PATTERN.search(block)
        or re.search(r"(unit\s+price|unit\s+cost|total\s+price|total\s+cost|award\s+amount|extended\s+price)", block, re.IGNORECASE)
    )
    if not has_price_context:
        return None
    prices = [_money(match.group(0)) for match in MONEY_PATTERN.finditer(block)]
    prices = [price for price in prices if price is not None and price > 0]
    if not prices:
        return None
    qty = _number_near(["QTY", "QUANTITY", "ORDER\\s+QTY"], block)
    unit_price = _number_near(["UNIT\\s+PRICE", "UNIT\\s+COST"], block)
    total_price = _number_near(["TOTAL\\s+PRICE", "TOTAL\\s+COST", "AWARD\\s+AMOUNT", "AMOUNT"], block)

    if unit_price is None and total_price is None:
        if qty and len(prices) >= 2:
            total_price = max(prices)
            unit_price = min(prices)
        elif qty and prices:
            total_price = max(prices)
            unit_price = round(total_price / qty, 4) if qty else None
        elif prices:
            unit_price = min(prices)

    if unit_price is None and total_price and qty:
        unit_price = round(total_price / qty, 4)
    if total_price is None and unit_price and qty:
        total_price = round(unit_price * qty, 4)

    cage_match = CAGE_PATTERN.search(block)
    cage = cage_match.group(0).upper() if cage_match else None
    award_match = AWARD_PATTERN.search(block)
    date_match = DATE_PATTERN.search(block)
    nsn = _normalize_nsn(block) or fallback_nsn
    supplier_name = _supplier_before_cage(block, cage)
    if supplier_name and not _looks_like_supplier_name(supplier_name):
        supplier_name = None

    confidence = 55.0
    if unit_price:
        confidence += 15
    if qty:
        confidence += 10
    if cage:
        confidence += 10
    if date_match:
        confidence += 5
    if award_match:
        confidence += 5

    return {
        "nsn": nsn,
        "award_id": award_match.group(0).upper() if award_match else None,
        "award_date": date_match.group(0) if date_match else None,
        "supplier_name": supplier_name,
        "cage": cage,
        "quantity": qty,
        "total_price": total_price,
        "unit_price": unit_price,
        "confidence": min(confidence, 95.0),
        "raw_text": block,
    }


def _ai_parse_price_blocks(db: Session, blocks: list[str], fallback_nsn: str | None) -> list[dict[str, Any]]:
    api_key = get_effective_openai_api_key(db)
    if not api_key or not blocks:
        return []
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return []
    prompt = {
        "task": "Extract previous award or historical pricing facts from DLA RFQ text.",
        "rules": [
            "Return JSON only.",
            "Only include facts that explicitly contain a price or award amount.",
            "Do not guess prices.",
            "If unit_price is missing but quantity and total_price are present, compute unit_price.",
            "If no reliable facts are present, return {\"awards\": []}.",
        ],
        "schema": {
            "awards": [
                {
                    "nsn": fallback_nsn,
                    "award_id": "string or null",
                    "award_date": "string or null",
                    "supplier_name": "string or null",
                    "cage": "string or null",
                    "quantity": "number or null",
                    "total_price": "number or null",
                    "unit_price": "number or null",
                    "confidence": "0-100",
                }
            ]
        },
        "text_blocks": blocks[:8],
    }
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=get_effective_openai_model(db),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You extract reliable government-contract pricing facts into strict JSON."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
    except Exception:
        return []
    facts = []
    for row in payload.get("awards") or []:
        unit_price = row.get("unit_price")
        total_price = row.get("total_price")
        qty = row.get("quantity")
        try:
            qty = float(qty) if qty is not None else None
            unit_price = float(unit_price) if unit_price is not None else None
            total_price = float(total_price) if total_price is not None else None
        except Exception:
            continue
        if unit_price is None and total_price is not None and qty:
            unit_price = round(total_price / qty, 4)
        if unit_price is None and total_price is None:
            continue
        facts.append({
            "nsn": _normalize_nsn(row.get("nsn")) or fallback_nsn,
            "award_id": _clean(row.get("award_id"), 120),
            "award_date": _clean(row.get("award_date"), 40),
            "supplier_name": _clean(row.get("supplier_name"), 240) if _looks_like_supplier_name(row.get("supplier_name")) else None,
            "cage": _clean(row.get("cage"), 20),
            "quantity": qty,
            "total_price": total_price,
            "unit_price": unit_price,
            "confidence": min(max(float(row.get("confidence") or 70), 0), 95),
            "raw_text": "AI extracted from candidate pricing blocks.",
        })
    return facts


def _upsert_price_fact(db: Session, opp: Opportunity, file_record: OpportunityFile, fact: dict[str, Any]) -> tuple[bool, bool]:
    if BAD_SUPPLIER_TEXT_PATTERN.search(fact.get("raw_text") or ""):
        return False, False
    if fact.get("cage") and not fact.get("award_id") and not fact.get("supplier_name"):
        sam_name, _ = _sam_supplier_for_cage(db, fact.get("cage"))
        if not sam_name:
            return False, False
    query = db.query(PriceHistory).filter(
        PriceHistory.opportunity_id == opp.id,
        PriceHistory.source_file_id == file_record.id,
        PriceHistory.cage == fact.get("cage"),
        PriceHistory.unit_price == fact.get("unit_price"),
    )
    if fact.get("award_id"):
        query = query.filter(PriceHistory.award_id == fact.get("award_id"))
    existing = query.first()
    if existing:
        touched = False
        for field in ["nsn", "award_date", "supplier_name", "quantity", "total_price", "source_label", "raw_text"]:
            value = fact.get(field)
            if value and not getattr(existing, field):
                setattr(existing, field, value)
                touched = True
        if fact.get("confidence") and (existing.confidence or 0) < fact["confidence"]:
            existing.confidence = fact["confidence"]
            touched = True
        if touched:
            db.add(existing)
            return False, True
        return False, False

    db.add(PriceHistory(
        organization_id=getattr(opp, "organization_id", None),
        opportunity_id=opp.id,
        source_file_id=file_record.id,
        nsn=fact.get("nsn"),
        award_id=fact.get("award_id"),
        award_date=fact.get("award_date"),
        supplier_name=fact.get("supplier_name"),
        cage=fact.get("cage"),
        quantity=fact.get("quantity"),
        total_price=fact.get("total_price"),
        unit_price=fact.get("unit_price"),
        source_label=file_record.filename,
        confidence=fact.get("confidence"),
        raw_text=fact.get("raw_text"),
    ))
    return True, False


def extract_price_history_for_opportunity(db: Session, opp: Opportunity) -> dict[str, Any]:
    fallback_nsn = _normalize_nsn(getattr(opp, "solicitation_number", None)) or _normalize_nsn(getattr(opp, "title", None))
    files = (
        db.query(OpportunityFile)
        .filter(OpportunityFile.opportunity_id == opp.id)
        .order_by(OpportunityFile.created_at.desc(), OpportunityFile.id.desc())
        .all()
    )
    created = 0
    updated = 0
    scanned_files = 0
    blocks_found = 0
    parsed_facts = 0
    provider_repo = ProviderRepository(db, organization_id=getattr(opp, "organization_id", None))
    ai_fallback_used = False

    for file_record in files:
        if not str(file_record.filename or "").lower().endswith(".pdf"):
            continue
        scanned_files += 1
        if file_record.extracted_text:
            text = file_record.extracted_text
        else:
            with local_temp_path(file_record.file_path, suffix=Path(file_record.filename or file_record.file_path).suffix) as local_path:
                text = _extract_text_with_pdfplumber(str(local_path))
        if not text:
            continue
        blocks = _candidate_blocks(text)
        blocks_found += len(blocks)
        file_facts = []
        for block in blocks:
            fact = _parse_block(block, fallback_nsn)
            if not fact or not fact.get("unit_price"):
                continue
            file_facts.append(fact)
        if not file_facts:
            ai_facts = _ai_parse_price_blocks(db, blocks, fallback_nsn)
            if ai_facts:
                ai_fallback_used = True
                file_facts.extend(ai_facts)
        for fact in file_facts:
            parsed_facts += 1
            was_created, was_updated = _upsert_price_fact(db, opp, file_record, fact)
            created += 1 if was_created else 0
            updated += 1 if was_updated else 0
            sam_name, sam_website = _sam_supplier_for_cage(db, fact.get("cage"))
            supplier_name = sam_name or fact.get("supplier_name")
            if supplier_name and _looks_like_supplier_name(supplier_name):
                try:
                    provider_repo.create(
                        ProviderCreate(
                            company_name=supplier_name,
                            cage=fact.get("cage"),
                            website=sam_website,
                            item=ProviderItemCreate(
                                nsn=fact.get("nsn"),
                                fsc=(fact.get("nsn") or "")[:4] or getattr(opp, "fsc", None),
                                nomenclature=getattr(opp, "title", None),
                                relationship_type="Historical Supplier",
                                source="DIBBS Price History",
                                source_url=file_record.source_url,
                                confidence=fact.get("confidence"),
                                notes=f"Historical unit price: {fact.get('unit_price')}",
                            ),
                        )
                    )
                except Exception:
                    db.rollback()

    if created or updated:
        db.commit()
    return {
        "scanned_files": scanned_files,
        "blocks_found": blocks_found,
        "parsed_facts": parsed_facts,
        "created": created,
        "updated": updated,
        "ai_fallback_used": ai_fallback_used,
    }


def summarize_price_history(db: Session, opportunity_id: int) -> dict[str, Any]:
    rows = (
        db.query(PriceHistory)
        .filter(PriceHistory.opportunity_id == opportunity_id)
        .filter(PriceHistory.unit_price.is_not(None))
        .order_by(PriceHistory.award_date.desc().nullslast(), PriceHistory.id.desc())
        .all()
    )
    rows = [
        row
        for row in rows
        if not BAD_SUPPLIER_TEXT_PATTERN.search(row.raw_text or "")
        and not (
            row.cage
            and not row.award_id
            and not row.supplier_name
            and not _sam_supplier_for_cage(db, row.cage)[0]
        )
    ]
    prices = [float(row.unit_price) for row in rows if row.unit_price is not None and row.unit_price > 0]
    totals = [float(row.total_price) for row in rows if row.total_price is not None and row.total_price > 0]
    return {
        "count": len(rows),
        "average_unit_price": round(mean(prices), 4) if prices else None,
        "low_unit_price": round(min(prices), 4) if prices else None,
        "high_unit_price": round(max(prices), 4) if prices else None,
        "average_total_award_amount": round(mean(totals), 2) if totals else None,
        "low_total_award_amount": round(min(totals), 2) if totals else None,
        "high_total_award_amount": round(max(totals), 2) if totals else None,
        "last_award": {
            "award_date": rows[0].award_date,
            "supplier_name": rows[0].supplier_name,
            "cage": rows[0].cage,
            "unit_price": rows[0].unit_price,
            "quantity": rows[0].quantity,
            "award_id": rows[0].award_id,
        } if rows else None,
        "items": [
            {
                "id": row.id,
                "nsn": row.nsn,
                "award_date": row.award_date,
                "supplier_name": row.supplier_name,
                "cage": row.cage,
                "quantity": row.quantity,
                "total_price": row.total_price,
                "unit_price": row.unit_price,
                "source_label": row.source_label,
                "confidence": row.confidence,
            }
            for row in rows[:10]
        ],
    }
