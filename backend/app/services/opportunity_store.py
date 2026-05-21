from app.utils.title_normalizer import normalize_source_title
from sqlalchemy.orm import Session
from app.models.opportunity import Opportunity
from app.services.dibbs_details import normalize_solicitation_number


def upsert_opportunity(db: Session, data: dict) -> Opportunity:
    source = str(data["source"])
    sol = normalize_solicitation_number(str(data["solicitation_number"]))

    existing = (
        db.query(Opportunity)
        .filter(Opportunity.source == source, Opportunity.solicitation_number == sol)
        .first()
    )

    if existing:
        existing.title = data.get("title") or existing.title
        existing.agency = data.get("agency") or existing.agency
        existing.url = data.get("url") or existing.url
        existing.posted_at = data.get("posted_at", existing.posted_at)
        existing.due_at = data.get("due_at", existing.due_at)
        existing.naics = data.get("naics", existing.naics)
        existing.fsc = data.get("fsc", existing.fsc)
        existing.set_aside = data.get("set_aside", existing.set_aside)
        existing.raw_text = data.get("raw_text", existing.raw_text)
        existing.raw_payload = data.get("raw_payload") or existing.raw_payload
        existing.source_opportunity_id = data.get("source_opportunity_id") or existing.source_opportunity_id
        return existing

    opp = Opportunity(
        source=source,
        source_opportunity_id=data.get("source_opportunity_id"),
        solicitation_number=sol,
        title=data.get("title") or "",
        agency=data.get("agency") or "DLA (DIBBS)",
        url=(data.get("url") or "")[:500],
        posted_at=data.get("posted_at"),
        due_at=data.get("due_at"),
        naics=data.get("naics"),
        fsc=data.get("fsc"),
        set_aside=data.get("set_aside"),
        raw_text=data.get("raw_text"),
        raw_payload=data.get("raw_payload"),
        status="new",
    )
    db.add(opp)
    return opp


def _clean_saved_title(value: str | None) -> str | None:
    if value is None:
        return value
    return value.replace("â€”", "—").replace("â€“", "–").replace("â", "—")
