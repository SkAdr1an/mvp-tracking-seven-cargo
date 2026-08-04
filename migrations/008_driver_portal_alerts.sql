PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS portal_alert_presentations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_link_id TEXT NOT NULL REFERENCES public_trip_links(id),
    alert_key TEXT NOT NULL,
    distance_band TEXT NOT NULL,
    severity TEXT NOT NULL,
    first_presented_at TEXT NOT NULL,
    last_presented_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    presentation_count INTEGER NOT NULL DEFAULT 1 CHECK (presentation_count >= 1),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    UNIQUE(public_link_id, alert_key)
);

CREATE INDEX IF NOT EXISTS idx_portal_alert_link_active
ON portal_alert_presentations(public_link_id, active, last_seen_at DESC);
