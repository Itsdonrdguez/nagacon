from sqlalchemy.exc import ProgrammingError

def get_analytics_summary(db):
    try:
        from app.models.pipeline_item import PipelineItem
        pipeline_items = db.query(PipelineItem).all()
        pipeline_count = len(pipeline_items)
    except Exception:
        pipeline_count = 0

    return {
        "pipeline_count": pipeline_count,
        "status": "ok"
    }
