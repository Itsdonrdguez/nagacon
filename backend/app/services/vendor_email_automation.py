from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.models.vendor import VendorLead, VendorQuote


def _safe(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _get_opp(db: Session, opportunity_id: int) -> Opportunity:
    opp = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opp:
        raise ValueError("Opportunity not found")
    return opp


def _email_subject(opp: Opportunity, company_name: str | None) -> str:
    sol = _safe(getattr(opp, "solicitation_number", ""))
    title = _safe(getattr(opp, "title", ""))
    suffix = f" - {company_name}" if company_name else ""
    return f"Quote Request: {sol} {title}{suffix}".strip()


def generate_quote_request_email(opportunity_id: int, db: Session, vendor_quote_id: int | None = None, vendor_lead_id: int | None = None) -> dict:
    opp = _get_opp(db, opportunity_id)

    quote = None
    lead = None

    if vendor_quote_id is not None:
        quote = db.query(VendorQuote).filter(
            VendorQuote.id == vendor_quote_id,
            VendorQuote.opportunity_id == opportunity_id,
        ).first()
        if not quote:
            raise ValueError("Vendor quote not found")

    if vendor_lead_id is not None:
        lead = db.query(VendorLead).filter(
            VendorLead.id == vendor_lead_id,
            VendorLead.opportunity_id == opportunity_id,
        ).first()
        if not lead:
            raise ValueError("Vendor lead not found")

    raw_payload = getattr(opp, "raw_payload", None) or {}
    dibbs_detail = raw_payload.get("dibbs_detail") or {}
    selected_sol = raw_payload.get("dibbs_selected_solicitation") or {}

    company_name = _safe(getattr(quote, "company_name", None) or getattr(lead, "company_name", None))
    contact_name = _safe(getattr(quote, "contact_name", None))
    email = _safe(getattr(quote, "email", None))
    phone = _safe(getattr(quote, "phone", None))
    cage = _safe(getattr(quote, "cage", None) or getattr(lead, "cage", None))
    part_number = _safe(getattr(quote, "part_number", None) or getattr(lead, "part_number", None))
    nsn = _safe(getattr(lead, "nsn", None) or dibbs_detail.get("nsn"))
    qty = _safe(selected_sol.get("qty"))
    pdf_url = _safe(selected_sol.get("pdf_url"))
    due_at = _safe(getattr(opp, "due_at", None)) or _safe(selected_sol.get("return_by_date"))
    agency = _safe(getattr(opp, "agency", None))
    solicitation = _safe(getattr(opp, "solicitation_number", None))
    title = _safe(getattr(opp, "title", None))

    subject = _email_subject(opp, company_name)

    body = f"""Hello {contact_name or company_name or "Team"},

We are requesting a quote in support of the following opportunity:

Solicitation: {solicitation}
Title: {title}
Agency: {agency}
Due Date: {due_at or "Please confirm current deadline"}
Opportunity URL: {_safe(getattr(opp, "url", ""))}
Official PDF: {pdf_url or "Available on request"}

Requested item details:
- NSN: {nsn or "Please confirm"}
- Part Number: {part_number or "Please confirm"}
- CAGE: {cage or "Please confirm"}
- Quantity: {qty or "Please confirm"}

Please provide:
1. Unit price
2. Lead time / availability
3. Shipping terms
4. Any minimum order requirements
5. Quote validity period

Thank you,
[Your Name]
[Your Company]
[Phone]
[Email]
"""

    return {
        "opportunity_id": opportunity_id,
        "vendor_quote_id": vendor_quote_id,
        "vendor_lead_id": vendor_lead_id,
        "to": email,
        "company_name": company_name,
        "phone": phone,
        "subject": subject,
        "body": body,
        "pdf_url": pdf_url,
        "nsn": nsn,
        "qty": qty,
        "solicitation_number": solicitation,
    }
