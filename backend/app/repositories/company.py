from sqlalchemy.exc import SQLAlchemyError
from app.models.company_profile import CompanyProfile


class CompanyRepository:
    def __init__(self, db):
        self.db = db

    def get_profile(self, profile_id):
        try:
            return self.db.query(CompanyProfile).filter(CompanyProfile.id == profile_id).first()
        except SQLAlchemyError:
            self.db.rollback()
            return None

    def upsert_profile(self, payload: dict):
        try:
            profile_id = payload.get("id")
            rec = None
            if profile_id is not None:
                rec = self.db.query(CompanyProfile).filter(CompanyProfile.id == profile_id).first()

            if rec is None:
                rec = CompanyProfile(**payload)
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
