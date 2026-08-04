-- Schema reference for the public-trip migration.
-- Apply it with `python -m scripts.migrate_public_trip`, which checks existing
-- SQLite columns and is safe to execute repeatedly. SQLite does not support
-- `ADD COLUMN IF NOT EXISTS`, so the ALTER statements intentionally live in
-- the idempotent Python migration runner instead of this reference file.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS public_trip_links (
    id TEXT PRIMARY KEY,
    trip_key TEXT NOT NULL REFERENCES operational_trips(trip_key),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    last_access_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    created_by TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_public_trip_links_one_active
ON public_trip_links(trip_key) WHERE active = 1;
CREATE INDEX IF NOT EXISTS idx_public_trip_links_hash
ON public_trip_links(token_hash);

CREATE TABLE IF NOT EXISTS public_trip_link_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_link_id TEXT NOT NULL REFERENCES public_trip_links(id),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    actor TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
