ALTER TABLE operational_trips ADD COLUMN cancelled_at TEXT;
ALTER TABLE operational_trips ADD COLUMN cancelled_by_user_id TEXT REFERENCES users(id);
ALTER TABLE operational_trips ADD COLUMN cancelled_reason TEXT;
ALTER TABLE operational_trips ADD COLUMN archived_at TEXT;
ALTER TABLE operational_trips ADD COLUMN archived_by_user_id TEXT REFERENCES users(id);
ALTER TABLE operational_trips ADD COLUMN archive_reason TEXT;

CREATE INDEX idx_operational_trips_state_archived
ON operational_trips(state, archived_at);

CREATE INDEX idx_operational_trips_archived_at
ON operational_trips(archived_at);
