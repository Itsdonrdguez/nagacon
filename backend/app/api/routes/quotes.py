from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.repositories.quotes import QuoteRepository
from app.schemas.quote import QuoteCreate, QuoteOut, QuoteUpdate
from app.services.quotes.calculations import create_quote_with_calc, update_quote_with_calc

router = APIRouter(prefix="/api/quotes", tags=["quotes"])


@router.get("/opportunities/{opportunity_id}", response_model=List[QuoteOut])
def list_quotes(opportunity_id: int, db: Session = Depends(get_db)):
    return QuoteRepository(db).list_by_opportunity_id(opportunity_id)


@router.post("/", response_model=QuoteOut)
def create_quote(item: QuoteCreate, db: Session = Depends(get_db)):
    return create_quote_with_calc(item, db)


@router.patch("/{quote_id}", response_model=QuoteOut)
def update_quote(quote_id: int, item: QuoteUpdate, db: Session = Depends(get_db)):
    rec = update_quote_with_calc(quote_id, item, db)
    if not rec:
        raise HTTPException(status_code=404, detail="Quote not found")
    return rec


@router.delete("/{quote_id}", response_model=dict)
def delete_quote(quote_id: int, db: Session = Depends(get_db)):
    ok = QuoteRepository(db).delete(quote_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {"ok": True, "quote_id": quote_id}
