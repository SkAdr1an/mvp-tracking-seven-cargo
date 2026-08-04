-- Provider-neutral routing metadata. Existing geometry rows remain unchanged.
ALTER TABLE route_geometry_versions ADD COLUMN provider TEXT;
ALTER TABLE route_geometry_versions ADD COLUMN distance_m REAL;
ALTER TABLE route_geometry_versions ADD COLUMN duration_seconds REAL;
