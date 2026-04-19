from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.models.company_profile import CompanyProfile
from app.models.past_performance import PastPerformance
from app.services.org_service import ensure_default_organization


class CompanyRepository:
    def __init__(self, db):
        self.db = db

    def create_profile(self, item):
        try:
            org = ensure_default_organization(self.db)
            rec = CompanyProfile(**item.model_dump(), organization_id=getattr(org, "id", None))
            self.db.add(rec)
            self.db.commit()
            self.db.refresh(rec)
            return rec
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def get_profile(self, profile_id):
        try:
            return self.db.query(CompanyProfile).filter(CompanyProfile.id == profile_id).first()
        except SQLAlchemyError:
            self.db.rollback()
            return None

    def get_first_profile(self):
        try:
            org = ensure_default_organization(self.db)
            query = self.db.query(CompanyProfile)
            if org is not None:
                query = query.filter(CompanyProfile.organization_id == org.id)
            return query.order_by(CompanyProfile.id.asc()).first()
        except SQLAlchemyError:
            self.db.rollback()
            return None

    def update_profile(self, profile_id, item):
        try:
            rec = self.get_profile(profile_id)
            if rec is None:
                return None

            for key, value in item.model_dump(exclude_unset=True).items():
                setattr(rec, key, value)

            self.db.commit()
            self.db.refresh(rec)
            return rec
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def upsert_profile(self, payload: dict):
        try:
            org = ensure_default_organization(self.db)
            profile_id = payload.get("id")
            rec = None
            if profile_id is not None:
                rec = self.db.query(CompanyProfile).filter(CompanyProfile.id == profile_id).first()

            if rec is None:
                rec = CompanyProfile(**payload, organization_id=getattr(org, "id", None))
                self.db.add(rec)
            else:
                for key, value in payload.items():
                    setattr(rec, key, value)

            self.db.commit()
            self.db.refresh(rec)
            return rec
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def create_past_performance(self, item):
        try:
            rec = PastPerformance(**item.model_dump())
            self.db.add(rec)
            self.db.commit()
            self.db.refresh(rec)
            return rec
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def list_past_performance(self, profile_id):
        try:
            return (
                self.db.query(PastPerformance)
                .filter(PastPerformance.company_profile_id == profile_id)
                .order_by(PastPerformance.id.desc())
                .all()
            )
        except SQLAlchemyError:
            self.db.rollback()
            return []

    def update_past_performance(self, perf_id, item):
        try:
            rec = self.db.query(PastPerformance).filter(PastPerformance.id == perf_id).first()
            if rec is None:
                return None

            for key, value in item.model_dump(exclude_unset=True).items():
                setattr(rec, key, value)

            self.db.commit()
            self.db.refresh(rec)
            return rec
        except SQLAlchemyError:
            self.db.rollback()
            raise
