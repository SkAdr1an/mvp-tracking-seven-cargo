CREATE TABLE IF NOT EXISTS journey_observation_trackers (
    trip_key TEXT PRIMARY KEY,
    candidate_started_at TEXT NOT NULL,
    candidate_latitude REAL NOT NULL,
    candidate_longitude REAL NOT NULL,
    last_position_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 1,
    stop_id INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operational_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_minutes REAL NOT NULL DEFAULT 0,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    classification TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_code TEXT,
    reason_text TEXT,
    evidence_source TEXT,
    confidence TEXT NOT NULL,
    confirmed_by TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operational_stops_trip_time
ON operational_stops(trip_key, started_at);

CREATE TABLE IF NOT EXISTS communication_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_minutes REAL NOT NULL,
    start_latitude REAL NOT NULL,
    start_longitude REAL NOT NULL,
    end_latitude REAL NOT NULL,
    end_longitude REAL NOT NULL,
    displacement_km REAL NOT NULL,
    interpretation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(trip_key, started_at, ended_at)
);

CREATE TABLE IF NOT EXISTS stop_evidence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stop_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    operator TEXT NOT NULL,
    justification TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operational_exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_key TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    first_detected_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution TEXT
);

CREATE INDEX IF NOT EXISTS idx_operational_exceptions_status
ON operational_exceptions(status, severity, last_seen_at);
