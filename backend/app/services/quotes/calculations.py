from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.quote import Quote
from app.repositories.quotes import QuoteRepository
from app.schemas.quote import QuoteCreate, QuoteUpdate


def apply_quote_calculations(rec: Quote) -> Quote:
    sell_price = float(rec.unit_cost or 0) * (1 + float(rec.markup_pct or 0) / 100.0)
    total_price = sell_price * float(rec.quantity or 0)

    rec.sell_price = round(sell_price, 2)
    rec.total_price = round(total_price, 2)
    return rec


def create_quote_with_calc(item: QuoteCreate, db: Session) -> Quote:
    repo = QuoteRepository(db)
    rec = repo.create(item)
    rec = apply_quote_calculations(rec)
    return repo.save(rec)


def update_quote_with_calc(quote_id: int, item: QuoteUpdate, db: Session) -> Optional[Quote]:
    repo = QuoteRepository(db)
    rec = repo.update(quote_id, item)
    if not rec:
        return None
    rec = apply_quote_calculations(rec)
    return repo.save(rec)
