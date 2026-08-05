-- Idempotent forward migration for canonical corridor recognition.
-- Rollback: drop trip_corridor_associations, trip_provider_metadata and
-- corridor_catalog in that order. No existing table or column is modified.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS corridor_catalog (
 route_id TEXT PRIMARY KEY REFERENCES route_configs(id),
 canonical_name TEXT NOT NULL, direction TEXT NOT NULL,
 origin_aliases_json TEXT NOT NULL, destination_aliases_json TEXT NOT NULL,
 route_aliases_json TEXT NOT NULL DEFAULT '[]', route_codes_json TEXT NOT NULL DEFAULT '[]',
 observed_origin_latitude REAL, observed_origin_longitude REAL,
 observed_destination_latitude REAL, observed_destination_longitude REAL,
 deviation_tolerance_m REAL NOT NULL DEFAULT 300,
 rules_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
 configuration_source TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_provider_metadata (
 trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
 provider TEXT NOT NULL, provider_trip_id TEXT, provider_code TEXT,
 metadata_json TEXT NOT NULL, provider_updated_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_corridor_associations (
 trip_key TEXT PRIMARY KEY REFERENCES operational_trips(trip_key),
 route_id TEXT REFERENCES route_configs(id), status TEXT NOT NULL,
 method TEXT NOT NULL, confidence TEXT NOT NULL, reason TEXT NOT NULL,
 evidence_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_corridor_association_status
ON trip_corridor_associations(status,updated_at);
