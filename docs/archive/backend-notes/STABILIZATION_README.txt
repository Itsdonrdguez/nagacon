NagaCon stabilization patch

Included fixes:
- opportunities list no longer crashes when pipeline_items table is missing
- workspace summary rolls back failed optional pipeline/vendor-match queries
- VendorMatchRepository now includes create_or_update
- backend .env is auto-loaded from backend root
- Streamlit opportunities/workspace pages now fail gracefully instead of hard-crashing

Recommended one-time database step:
Run SQL_CREATE_PIPELINE_ITEMS.sql against your Postgres database.
