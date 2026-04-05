from __future__ import annotations

from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.quote import Quote
from app.schemas.quote import QuoteCreate, QuoteUpdate


class QuoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, quote_id: int) -> Optional[Quote]:
        try:
            return self.db.query(Quote).filter(Quote.id == quote_id).first()
        except SQLAlchemyError:
            self.db.rollback()
            return None

    def list_by_opportunity_id(self, opportunity_id: int) -> List[Quote]:
        try:
            return (
                self.db.query(Quote)
                .filter(Quote.opportunity_id == opportunity_id)
                .order_by(Quote.created_at.desc())
                .all()
            )
        except SQLAlchemyError:
            self.db.rollback()
            return []

    def create(self, item: QuoteCreate) -> Quote:
        rec = Quote(**item.model_dump())
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def update(self, quote_id: int, item: QuoteUpdate) -> Optional[Quote]:
        rec = self.get(quote_id)
        if not rec:
            return None

        for key, value in item.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(rec, key, value)

        self.db.commit()
        self.db.refresh(rec)
        return rec

    def save(self, rec: Quote) -> Quote:
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def delete(self, quote_id: int) -> bool:
        rec = self.get(quote_id)
        if not rec:
            return False
        self.db.delete(rec)
        self.db.commit()
        return True
