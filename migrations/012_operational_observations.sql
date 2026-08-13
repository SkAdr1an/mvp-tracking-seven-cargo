CREATE TABLE IF NOT EXISTS operational_observations (
    id TEXT PRIMARY KEY,
    trip_key TEXT NOT NULL REFERENCES operational_trips(trip_key) ON UPDATE RESTRICT ON DELETE RESTRICT,
    observation_type TEXT NOT NULL CHECK(observation_type IN (
        'GENERAL', 'STOP', 'DRIVER_CONTACT', 'GR_INTERVENTION', 'INCIDENT', 'OPERATIONAL_NOTE'
    )),
    content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 4000),
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by_user_id TEXT NOT NULL REFERENCES users(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    author_username_snapshot TEXT NOT NULL,
    author_display_name_snapshot TEXT NOT NULL,
    author_role_snapshot TEXT NOT NULL CHECK(author_role_snapshot IN ('ADMIN', 'GR', 'MONITORING')),
    stop_id INTEGER REFERENCES operational_stops(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    include_in_report INTEGER NOT NULL DEFAULT 1 CHECK(include_in_report IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'CORRECTED', 'VOIDED')),
    corrected_by_user_id TEXT REFERENCES users(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    corrected_at TEXT,
    correction_reason TEXT,
    supersedes_observation_id TEXT REFERENCES operational_observations(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    voided_by_user_id TEXT REFERENCES users(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    voided_at TEXT,
    void_reason TEXT,
    created_from TEXT,
    metadata_json TEXT,
    CHECK(
        (observation_type = 'STOP' AND stop_id IS NOT NULL)
        OR (observation_type <> 'STOP' AND stop_id IS NULL)
    ),
    CHECK(
        (status = 'ACTIVE' AND corrected_at IS NULL AND voided_at IS NULL)
        OR (status = 'CORRECTED' AND corrected_by_user_id IS NOT NULL AND corrected_at IS NOT NULL
            AND length(trim(correction_reason)) > 0 AND voided_at IS NULL)
        OR (status = 'VOIDED' AND voided_by_user_id IS NOT NULL AND voided_at IS NOT NULL
            AND length(trim(void_reason)) > 0 AND corrected_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_operational_observations_trip_time
ON operational_observations(trip_key, occurred_at, created_at, id);

CREATE INDEX IF NOT EXISTS idx_operational_observations_author_time
ON operational_observations(created_by_user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_operational_observations_stop
ON operational_observations(stop_id) WHERE stop_id IS NOT NULL;
