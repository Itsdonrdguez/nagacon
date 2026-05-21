from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_organization, get_current_user, get_db
from app.models.opportunity import Opportunity
from app.models.quote import Quote
from app.repositories.quotes import QuoteRepository
from app.schemas.quote import QuoteCreate, QuoteOut, QuoteUpdate
from app.services.quotes.calculations import create_quote_with_calc, update_quote_with_calc

router = APIRouter(
    prefix="/api/quotes",
    tags=["quotes"],
    dependencies=[Depends(get_current_user), Depends(get_current_organization)],
)


def _scoped_opportunity(db: Session, opportunity_id: int, organization_id: int | None) -> Opportunity:
    query = db.query(Opportunity).filter(Opportunity.id == opportunity_id)
    if organization_id is not None:
        query = query.filter(or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)))
    opp = query.first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if organization_id is not None and getattr(opp, "organization_id", None) is None:
        opp.organization_id = organization_id
        db.add(opp)
        db.commit()
        db.refresh(opp)
    return opp


def _scoped_quote(db: Session, quote_id: int, organization_id: int | None) -> Quote:
    query = db.query(Quote).join(Opportunity, Opportunity.id == Quote.opportunity_id).filter(Quote.id == quote_id)
    if organization_id is not None:
        query = query.filter(or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)))
    quote = query.first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    if organization_id is not None:
        opp = db.query(Opportunity).filter(Opportunity.id == quote.opportunity_id).first()
        if opp and getattr(opp, "organization_id", None) is None:
            opp.organization_id = organization_id
            db.add(opp)
            db.commit()
            db.refresh(opp)
            db.refresh(quote)
    return quote


@router.get("/opportunities/{opportunity_id}", response_model=List[QuoteOut])
def list_quotes(opportunity_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    _scoped_opportunity(db, opportunity_id, getattr(current_org, "id", None))
    return QuoteRepository(db).list_by_opportunity_id(opportunity_id)


@router.post("/", response_model=QuoteOut)
def create_quote(item: QuoteCreate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    _scoped_opportunity(db, item.opportunity_id, getattr(current_org, "id", None))
    return create_quote_with_calc(item, db)


@router.patch("/{quote_id}", response_model=QuoteOut)
def update_quote(quote_id: int, item: QuoteUpdate, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    _scoped_quote(db, quote_id, getattr(current_org, "id", None))
    rec = update_quote_with_calc(quote_id, item, db)
    if not rec:
        raise HTTPException(status_code=404, detail="Quote not found")
    return rec


@router.delete("/{quote_id}", response_model=dict)
def delete_quote(quote_id: int, db: Session = Depends(get_db), current_org=Depends(get_current_organization)):
    _scoped_quote(db, quote_id, getattr(current_org, "id", None))
    ok = QuoteRepository(db).delete(quote_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {"ok": True, "quote_id": quote_id}
