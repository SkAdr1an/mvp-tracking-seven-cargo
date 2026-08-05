PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS portal_mobile_position_metadata (
    position_id INTEGER PRIMARY KEY
        REFERENCES operational_positions(id) ON DELETE CASCADE,
    public_link_id TEXT NOT NULL
        REFERENCES public_trip_links(id),
    accuracy_m REAL NOT NULL CHECK (accuracy_m >= 0 AND accuracy_m <= 10000),
    client_recorded_at TEXT,
    received_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portal_mobile_link_received
ON portal_mobile_position_metadata(public_link_id, received_at DESC);
