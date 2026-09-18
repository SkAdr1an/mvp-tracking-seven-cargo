CREATE TABLE IF NOT EXISTS route_alternatives (
    id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES route_configs(id),
    name TEXT NOT NULL,
    direction TEXT NOT NULL,
    origin_name TEXT NOT NULL,
    destination_name TEXT NOT NULL,
    geometry_json TEXT,
    total_distance_km REAL,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL,
    version TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_route_alternatives_route_active
ON route_alternatives(route_id, active, validation_status);

CREATE TABLE IF NOT EXISTS route_alternative_selections (
    trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
    route_id TEXT NOT NULL REFERENCES route_configs(id),
    alternative_id TEXT REFERENCES route_alternatives(id),
    reason TEXT NOT NULL,
    confidence TEXT NOT NULL,
    candidate_id TEXT REFERENCES route_alternatives(id),
    candidate_count INTEGER NOT NULL DEFAULT 0,
    changed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_route_alternative_selections_route
ON route_alternative_selections(route_id, alternative_id);
