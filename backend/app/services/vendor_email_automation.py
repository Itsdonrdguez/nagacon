from __future__ import annotations

import smtplib
from email.message import EmailMessage
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
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
    nsn = _safe((getattr(opp, "raw_payload", None) or {}).get("dibbs_detail", {}).get("nsn"))
    title = _safe(getattr(opp, "title", ""))
    core = sol or title or "Government Opportunity"
    qualifier = f" | NSN {nsn}" if nsn else ""
    suffix = f" | {company_name}" if company_name else ""
    return f"Quote Request | {core}{qualifier}{suffix}".strip()


def _format_display_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y")
    text = str(value).strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m-%d-%Y", "%Y %b %d", "%Y %b %d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%b %d, %Y")
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return text


def _build_quote_request_body(
    *,
    recipient_name: str | None,
    solicitation: str,
    title: str,
    agency: str,
    due_at: str,
    nsn: str,
    quantity: str,
    item_name: str,
    part_number: str,
    cage: str,
    pr_number: str = "",
) -> str:
    requested_details = [
        ("Solicitation", solicitation or "Please confirm"),
        ("Agency", agency or "Agency unavailable"),
        ("Item", item_name or title or "Please confirm"),
        ("NSN", nsn or "Please confirm"),
        ("Quantity", quantity or "Please confirm"),
        ("Response Due", _format_display_date(due_at) or due_at or "Please confirm current deadline"),
    ]
    if pr_number:
        requested_details.append(("PR Number", pr_number))

    if part_number:
        requested_details.append(("Known Part Number", part_number))
    if cage:
        requested_details.append(("Known CAGE", cage))

    detail_lines = "".join(f"- {label}: {value}\n" for label, value in requested_details if value)

    requested_quote_items = [
        "- Unit price",
        "- Available quantity and lead time",
        "- Manufacturer name and quoted part number",
        "- CAGE code",
        "- Shipping / FOB terms",
        "- Any minimum order quantity, quote validity period, or supply constraints",
    ]

    return (
        f"Hello {recipient_name or 'Team'},\n\n"
        "We are requesting a quotation in support of the government opportunity below.\n\n"
        "Opportunity Details\n"
        f"{detail_lines}\n"
        "Please include the following in your quote:\n"
        + "\n".join(requested_quote_items)
        + "\n\n"
        "If you can support this requirement, please reply with your pricing and availability at your earliest convenience.\n\n"
        "Thank you,\n"
        "[Your Name]\n"
        "[Your Company]\n"
        "[Phone]\n"
        "[Email]\n"
    )


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
    pr_number = _safe(selected_sol.get("pr_number"))

    subject = _email_subject(opp, company_name)
    body = _build_quote_request_body(
        recipient_name=contact_name or company_name or "Team",
        solicitation=solicitation,
        title=title,
        agency=agency,
        due_at=due_at,
        nsn=nsn,
        quantity=qty,
        item_name=title,
        part_number=part_number,
        cage=cage,
        pr_number=pr_number,
    )

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


def send_email_message(to_email: str, subject: str, body: str) -> dict:
    host = getattr(settings, "SMTP_HOST", None)
    port = getattr(settings, "SMTP_PORT", None)
    username = getattr(settings, "SMTP_USERNAME", None)
    password = getattr(settings, "SMTP_PASSWORD", None)
    from_email = getattr(settings, "SMTP_FROM_EMAIL", None) or username
    use_tls = bool(getattr(settings, "SMTP_USE_TLS", True))

    if not host or not port or not from_email:
        raise ValueError("SMTP is not configured. Set SMTP_HOST, SMTP_PORT, and SMTP_FROM_EMAIL.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=30) as server:
        if use_tls:
            server.starttls()
        if username and password:
            server.login(username, password)
        server.send_message(msg)

    return {
        "status": "sent",
        "to": to_email,
        "from": from_email,
        "subject": subject,
    }
