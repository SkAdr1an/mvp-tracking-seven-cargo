-- Neutral operational sites. Route roles remain in route_configs/operational_trips.
CREATE TABLE IF NOT EXISTS operational_sites (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    operation TEXT NOT NULL,
    latitude REAL NOT NULL CHECK(latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK(longitude BETWEEN -180 AND 180),
    approach_radius_m REAL NOT NULL DEFAULT 1000,
    entry_radius_m REAL NOT NULL DEFAULT 500,
    exit_radius_m REAL NOT NULL DEFAULT 650,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operational_site_aliases (
    alias_code TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES operational_sites(id),
    operation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vehicle_site_states (
    plate TEXT PRIMARY KEY,
    site_id TEXT REFERENCES operational_sites(id),
    state TEXT NOT NULL,
    distance_m REAL,
    latitude REAL,
    longitude REAL,
    position_at TEXT,
    stale INTEGER NOT NULL DEFAULT 0,
    diagnostic_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
