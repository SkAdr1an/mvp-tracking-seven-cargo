-- Explicit, directional route-to-site links. Existing route IDs and
-- geometries are preserved; repeated execution is safe.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS route_site_links (
    route_id TEXT PRIMARY KEY REFERENCES route_configs(id),
    origin_site_id TEXT NOT NULL REFERENCES operational_sites(id),
    destination_site_id TEXT NOT NULL REFERENCES operational_sites(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
