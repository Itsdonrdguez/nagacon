CREATE TABLE IF NOT EXISTS pipeline_items (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    decision_status VARCHAR(50),
    owner VARCHAR(255),
    priority VARCHAR(50),
    probability_of_win DOUBLE PRECISION,
    notes TEXT,
    target_submit_date TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL
);
