from sqlalchemy.exc import ProgrammingError
from app.models.pipeline_item import PipelineItem

class PipelineRepository:
    def __init__(self, db):
        self.db = db

    def get(self, pipeline_id):
        try:
            return self.db.query(PipelineItem).filter(PipelineItem.id == pipeline_id).first()
        except Exception:
            return None
