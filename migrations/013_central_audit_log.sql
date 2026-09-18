CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    actor_user_id TEXT REFERENCES users(id),
    actor_username_snapshot TEXT NOT NULL,
    actor_display_name_snapshot TEXT NOT NULL,
    actor_role_snapshot TEXT NOT NULL,
    action_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    trip_key TEXT,
    before_json TEXT,
    after_json TEXT,
    content TEXT,
    justification TEXT,
    request_id TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at ON audit_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor_time ON audit_events(actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_trip_time ON audit_events(trip_key, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_action_time ON audit_events(action_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_resource ON audit_events(resource_type, resource_id);
