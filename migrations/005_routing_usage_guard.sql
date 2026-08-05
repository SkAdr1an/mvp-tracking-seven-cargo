-- Routing consumption audit and persistent automatic retry guard.
-- No credentials, URLs or raw coordinates are stored.
CREATE TABLE IF NOT EXISTS routing_provision_attempts (
    route_id TEXT PRIMARY KEY,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    http_status INTEGER,
    error_code TEXT,
    message TEXT,
    last_attempt_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_fingerprint TEXT NOT NULL,
    context TEXT NOT NULL,
    travel_mode TEXT NOT NULL,
    traffic_enabled INTEGER NOT NULL,
    http_status INTEGER,
    result TEXT NOT NULL,
    latency_ms REAL,
    occurred_at TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'tomtom'
);

CREATE INDEX IF NOT EXISTS idx_routing_usage_time
ON routing_api_usage(occurred_at);
