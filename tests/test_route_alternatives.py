import json

from app.services.route_alternatives import RouteAlternativeService
from app.services.route_deviation import RouteDeviationService
from app.services.route_progress import RouteProgressService
from app.services.trip_operations import TripOperationsService
from app.storage.operations import OperationsRepository, utc_now


def services_at(tmp_path):
    repository=OperationsRepository(tmp_path/"operations.db");TripOperationsService(repository)
    repository.ensure_trip("trip:alt","ABC1D23","alt","betim-jaboatao")
    primary=[{"latitude":-20.0,"longitude":-44.0},{"latitude":-19.0,"longitude":-44.0}]
    alternative=[{"latitude":-20.0,"longitude":-43.99},{"latitude":-19.0,"longitude":-43.99}]
    now=utc_now()
    with repository.connect() as connection:
        connection.execute("INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?)",("betim-jaboatao","primary-v1","test",json.dumps(primary),"[]",300,"[]",1,now))
        connection.execute("INSERT INTO route_alternatives(id,route_id,name,direction,origin_name,destination_name,geometry_json,total_distance_km,source,source_url,validation_status,version,evidence_json,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",("authorized-alt","betim-jaboatao","Alternativa autorizada","teste","origem","destino",json.dumps(alternative),111,"test","","validated","alt-v1",json.dumps({"corridor_m":500}),1,now,now))
    return repository


def test_authorized_alternative_prevents_false_deviation_and_is_confirmed(tmp_path):
    repository=services_at(tmp_path);service=RouteDeviationService(repository)
    assert service.process("trip:alt","ABC1D23","betim-jaboatao",-19.5,-43.99,"2026-01-01T10:00:00+00:00") is None
    assert service.process("trip:alt","ABC1D23","betim-jaboatao",-19.49,-43.99,"2026-01-01T10:01:00+00:00") is None
    with repository.connect() as connection:
        selected=connection.execute("SELECT alternative_id,reason FROM route_alternative_selections WHERE trip_key='trip:alt'").fetchone()
    assert selected["alternative_id"]=="authorized-alt"
    assert selected["reason"]=="alternative_confirmed"


def test_progress_uses_nearest_authorized_geometry(tmp_path):
    repository=services_at(tmp_path)
    value=RouteProgressService(repository).calculate("trip:alt","betim-jaboatao",-19.5,-43.99,60,"2026-01-01T10:00:00+00:00",False)
    assert value["alternative_route"]
    assert value["route_variant"]=="authorized-alt"
    assert value["route_variant_name"]=="Alternativa autorizada"
    assert value["route_state"]=="ON_ROUTE"


def test_unvalidated_alternative_is_never_authorized(tmp_path):
    repository=services_at(tmp_path)
    with repository.connect() as connection:
        connection.execute("UPDATE route_alternatives SET validation_status='pending_validation'")
    resolved=RouteAlternativeService(repository).resolve("trip:alt","betim-jaboatao",-19.5,-43.99)
    assert resolved["id"]=="primary"
