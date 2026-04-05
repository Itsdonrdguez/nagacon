from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.vendor_opportunity_match import VendorOpportunityMatch


class VendorMatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_by_opportunity(self, opportunity_id: int) -> List[VendorOpportunityMatch]:
        return (
            self.db.query(VendorOpportunityMatch)
            .filter(VendorOpportunityMatch.opportunity_id == opportunity_id)
            .all()
        )

    # Compatibility alias for callers expecting this method name
    def list_by_opportunity_id(self, opportunity_id: int) -> List[VendorOpportunityMatch]:
        return self.list_by_opportunity(opportunity_id)

    def get(self, match_id: int) -> Optional[VendorOpportunityMatch]:
        return (
            self.db.query(VendorOpportunityMatch)
            .filter(VendorOpportunityMatch.id == match_id)
            .first()
        )

    def create(self, match: VendorOpportunityMatch) -> VendorOpportunityMatch:
        self.db.add(match)
        self.db.commit()
        self.db.refresh(match)
        return match

    def delete(self, match_id: int) -> Optional[VendorOpportunityMatch]:
        obj = self.get(match_id)
        if obj:
            self.db.delete(obj)
            self.db.commit()
        return obj


    def create_or_update(self, vendor_id, opportunity_id, **kwargs):
        rec = self.db.query(VendorOpportunityMatch).filter_by(
            vendor_id=vendor_id,
            opportunity_id=opportunity_id
        ).first()
        if rec:
            for k,v in kwargs.items():
                setattr(rec,k,v)
        else:
            rec = VendorOpportunityMatch(
                vendor_id=vendor_id,
                opportunity_id=opportunity_id,
                **kwargs
            )
            self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec
