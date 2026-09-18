-- Safe only before the feature contains production records. Validate the count first.
-- SELECT COUNT(*) FROM driver_evaluations;
-- SELECT COUNT(*) FROM punctuality_adjustments;
-- SELECT COUNT(*) FROM driver_internal_notes;
DROP TABLE IF EXISTS driver_trip_history_changes;
DROP TABLE IF EXISTS driver_identity_links;
DROP TABLE IF EXISTS driver_internal_notes;
DROP TABLE IF EXISTS punctuality_adjustments;
DROP TABLE IF EXISTS driver_evaluation_history;
DROP TABLE IF EXISTS driver_evaluations;
DROP TABLE IF EXISTS driver_trip_history;
DROP TABLE IF EXISTS driver_profiles;
