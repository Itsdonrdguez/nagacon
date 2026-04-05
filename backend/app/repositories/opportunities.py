from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.utils.exceptions import DuplicateRecordError


class OpportunityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, opportunity_id: int) -> Opportunity | None:
        return self.db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()

    def get_by_source_id(self, source: str, source_id: str) -> Opportunity | None:
        return (
            self.db.query(Opportunity)
            .filter(Opportunity.source == source, Opportunity.source_opportunity_id == source_id)
            .first()
        )

    def get_by_source_and_solicitation(self, source: str, solicitation_number: str) -> Opportunity | None:
        return (
            self.db.query(Opportunity)
            .filter(Opportunity.source == source, Opportunity.solicitation_number == solicitation_number)
            .first()
        )

    def find_dedupe_candidates(self, source: str, agency: str | None = None, limit: int = 100) -> list[Opportunity]:
        q = self.db.query(Opportunity).filter(Opportunity.source == source)
        if agency:
            q = q.filter(Opportunity.agency == agency)
        return q.order_by(Opportunity.id.desc()).limit(limit).all()

    def list(self, limit: int = 100, offset: int = 0) -> list[Opportunity]:
        return (
            self.db.query(Opportunity)
            .order_by(Opportunity.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def create(self, opp: OpportunityCreate) -> Opportunity:
        payload = opp.model_dump()
        db_opp = Opportunity(
            source=payload["source"],
            source_opportunity_id=payload.get("source_opportunity_id"),
            solicitation_number=payload.get("solicitation_number") or "",
            title=payload["title"],
            agency=payload.get("agency") or "",
            sub_agency=payload.get("sub_agency"),
            office=payload.get("office"),
            url=(payload.get("url") or "")[:500],
            posted_at=payload.get("posted_at"),
            due_at=payload.get("due_at"),
            naics=payload.get("naics_code"),
            fsc=payload.get("fsc_code"),
            set_aside=payload.get("set_aside_type"),
            place_of_performance=payload.get("place_of_performance"),
            raw_text=payload.get("description"),
            raw_payload=payload.get("raw_payload"),
            status=payload.get("status", "new").value if hasattr(payload.get("status"), "value") else str(payload.get("status", "new")),
        )
        self.db.add(db_opp)
        self.db.commit()
        self.db.refresh(db_opp)
        return db_opp

    def update(self, opportunity_id: int, opp_update: OpportunityUpdate) -> Opportunity | None:
        db_opp = self.get(opportunity_id)
        if not db_opp:
            return None
        update_data = opp_update.model_dump(exclude_unset=True)
        field_map = {
            "source_opportunity_id": "source_opportunity_id",
            "solicitation_number": "solicitation_number",
            "title": "title",
            "agency": "agency",
            "sub_agency": "sub_agency",
            "office": "office",
            "url": "url",
            "posted_at": "posted_at",
            "due_at": "due_at",
            "set_aside_type": "set_aside",
            "naics_code": "naics",
            "fsc_code": "fsc",
            "place_of_performance": "place_of_performance",
            "description": "raw_text",
            "raw_payload": "raw_payload",
            "status": "status",
        }
        for key, value in update_data.items():
            if value is None:
                continue
            attr = field_map.get(key)
            if not attr:
                continue
            if key == "status" and hasattr(value, "value"):
                value = value.value
            setattr(db_opp, attr, value)
        self.db.commit()
        self.db.refresh(db_opp)
        return db_opp

    def upsert(self, opp: OpportunityCreate) -> tuple[Opportunity, str]:
        existing = None
        if opp.source_opportunity_id:
            existing = self.get_by_source_id(opp.source, opp.source_opportunity_id)
        if not existing and opp.solicitation_number:
            existing = self.get_by_source_and_solicitation(opp.source, opp.solicitation_number)
        if existing:
            updated = self.update(existing.id, OpportunityUpdate(**opp.model_dump()))
            return updated, "updated"
        try:
            created = self.create(opp)
            return created, "inserted"
        except IntegrityError:
            self.db.rollback()
            key = opp.source_opportunity_id or opp.solicitation_number or opp.title
            raise DuplicateRecordError(f"Duplicate opportunity detected for {opp.source}/{key}")
