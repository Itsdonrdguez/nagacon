from sqlalchemy import text
from app.core.db import SessionLocal

sql = """
CREATE TABLE IF NOT EXISTS vendor_opportunity_matches (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL,
    opportunity_id INTEGER NOT NULL,
    match_reason TEXT,
    confidence_score DOUBLE PRECISION,
    source TEXT DEFAULT 'rule_based',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_vendor_opportunity_matches_vendor_id
ON vendor_opportunity_matches (vendor_id);

CREATE INDEX IF NOT EXISTS ix_vendor_opportunity_matches_opportunity_id
ON vendor_opportunity_matches (opportunity_id);
"""

db = SessionLocal()

db.execute(text(sql))
db.commit()

print("vendor_opportunity_matches table created")