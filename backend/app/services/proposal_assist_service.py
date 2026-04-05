from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead, VendorQuote


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _opp_payload(opp: Opportunity) -> dict:
    return {
        "id": opp.id,
        "source": _safe_text(getattr(opp, "source", "")),
        "solicitation_number": _safe_text(getattr(opp, "solicitation_number", "")),
        "title": _safe_text(getattr(opp, "title", "")),
        "agency": _safe_text(getattr(opp, "agency", "")),
        "url": _safe_text(getattr(opp, "url", "")),
        "description": _safe_text(getattr(opp, "description", getattr(opp, "raw_text", ""))),
        "naics_code": _safe_text(getattr(opp, "naics_code", getattr(opp, "naics", ""))),
        "fsc_code": _safe_text(getattr(opp, "fsc_code", getattr(opp, "fsc", ""))),
        "set_aside_type": _safe_text(getattr(opp, "set_aside_type", getattr(opp, "set_aside", ""))),
        "due_at": _safe_text(getattr(opp, "due_at", "")),
    }


def _lead_payload(lead: VendorLead) -> dict:
    return {
        "id": lead.id,
        "company_name": _safe_text(getattr(lead, "company_name", "")),
        "cage": _safe_text(getattr(lead, "cage", "")),
        "part_number": _safe_text(getattr(lead, "part_number", "")),
        "nsn": _safe_text(getattr(lead, "nsn", "")),
        "status": _safe_text(getattr(lead, "status", "")),
        "notes": _safe_text(getattr(lead, "notes", "")),
    }


def _quote_payload(quote: VendorQuote) -> dict:
    return {
        "id": quote.id,
        "company_name": _safe_text(getattr(quote, "company_name", "")),
        "cage": _safe_text(getattr(quote, "cage", "")),
        "part_number": _safe_text(getattr(quote, "part_number", "")),
        "contact_name": _safe_text(getattr(quote, "contact_name", "")),
        "email": _safe_text(getattr(quote, "email", "")),
        "phone": _safe_text(getattr(quote, "phone", "")),
        "status": _safe_text(getattr(quote, "status", "")),
        "unit_price": _safe_text(getattr(quote, "unit_price", "")),
        "lead_time_days": _safe_text(getattr(quote, "lead_time_days", "")),
        "notes": _safe_text(getattr(quote, "notes", "")),
    }


def _template_proposal(context: dict) -> str:
    opp = context["opportunity"]
    lead_names = ", ".join([x["company_name"] for x in context["vendor_leads"][:5] if x["company_name"]]) or "identified suppliers"
    quote_names = ", ".join([x["company_name"] for x in context["vendor_quotes"][:5] if x["company_name"]]) or "current vendor quotes"

    return f"""# Proposal Draft

## Executive Summary
We intend to submit a response for solicitation {opp["solicitation_number"]} titled "{opp["title"]}" issued by {opp["agency"] or "the agency"}.
This draft was generated from the current NagaCon workspace and reflects the opportunity record, parsed vendor leads, and available quote records.

## Opportunity Snapshot
- Source: {opp["source"]}
- Solicitation: {opp["solicitation_number"]}
- Agency: {opp["agency"]}
- Due Date: {opp["due_at"] or "TBD"}
- NAICS: {opp["naics_code"] or "N/A"}
- FSC: {opp["fsc_code"] or "N/A"}
- Set-Aside: {opp["set_aside_type"] or "N/A"}

## Technical / Supply Understanding
The opportunity appears to center on:
{opp["description"] or opp["title"]}

## Sourcing Position
Current supplier intelligence includes: {lead_names}.
Current quote coverage includes: {quote_names}.

## Pricing Position
Use vendor quotes already captured in the workspace to finalize the pricing narrative.
Where no quote exists yet, the team should request and log supplier pricing before final submission.

## Compliance / Next Steps
1. Verify item, NSN, part number, and row-level solicitation details.
2. Confirm approved source status where applicable.
3. Finalize vendor quote selection and pricing assumptions.
4. Prepare the final response package and submit before the due date.

## Draft Close
This draft is intended as a working proposal foundation and should be refined with final pricing, delivery, and compliance language before submission.
"""


def _try_openai_enhance(context: dict, fallback_text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback_text

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        prompt = (
            "You are a government contracting proposal writer. "
            "Rewrite the following internal proposal draft into a cleaner, professional government-contracting draft. "
            "Keep it concise and practical.\n\n"
            f"Context:\n{context}\n\n"
            f"Draft:\n{fallback_text}"
        )
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "Write practical proposal drafts for government contracting responses."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or fallback_text
    except Exception:
        return fallback_text


def generate_proposal_draft(opportunity_id: int, db: Session) -> dict:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ValueError("Opportunity not found")

    leads = (
        db.query(VendorLead)
        .filter(VendorLead.opportunity_id == opportunity_id)
        .order_by(VendorLead.company_name.asc())
        .all()
    )
    quotes = (
        db.query(VendorQuote)
        .filter(VendorQuote.opportunity_id == opportunity_id)
        .order_by(VendorQuote.company_name.asc())
        .all()
    )

    context = {
        "opportunity": _opp_payload(opp),
        "vendor_leads": [_lead_payload(x) for x in leads],
        "vendor_quotes": [_quote_payload(x) for x in quotes],
    }

    draft = _template_proposal(context)
    final_text = _try_openai_enhance(context, draft)

    return {
        "opportunity_id": opportunity_id,
        "draft_type": "proposal",
        "draft": final_text,
        "context": context,
    }
