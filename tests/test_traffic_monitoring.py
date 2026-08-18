from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.tomtom import AuthError, RateLimitError, UnavailableError
from app.services.traffic_monitoring import (
    ROUTE_GEOMETRIES, TrafficMonitoringService, associate_incident, densify,
    normalize_incident, remaining_route, route_projection,
)
from app.storage.operations import OperationsRepository
from app.storage.traffic import TrafficRepository


def raw_incident(identifier="one", point=(-19.6,-44.2), icon=1, end=None, direction="Norte"):
    return {"type":"Feature","geometry":{"type":"Point","coordinates":[point[1],point[0]]},"properties":{"id":identifier,"iconCategory":icon,"magnitudeOfDelay":3,"startTime":"2026-07-22T10:00:00Z","endTime":end or "2099-07-22T12:00:00Z","from":"BR-381","to":direction,"length":800,"delay":420,"events":[{"description":"Acidente"}]}}


def trip(point, plate="AAA1A11"):
    return {"plate":plate,"position":{"latitude":point[0],"longitude":point[1]},"operational":{"trip_key":f"trip:{plate}","route_id":"betim-jaboatao"},"prediction":{"eta_at":"2026-07-23T00:00:00Z"}}


class FakeClient:
    def __init__(self, payload=None, error=None): self.payload=payload or {"incidents":[]};self.error=error;self.boxes=[]
    async def get_traffic_incidents(self,bbox):
        self.boxes.append(bbox)
        if self.error: raise self.error
        return self.payload
    async def get_flow_segment(self,latitude,longitude): return {"flowSegmentData":{"currentSpeed":45},"_telemetry":{"status":200,"latency_ms":10}}

class FakeAzure:
    def __init__(self,payload=None,error=None):self.payload=payload or {"type":"FeatureCollection","features":[]};self.error=error;self.boxes=[]
    async def get_traffic_incidents(self,bbox):
        self.boxes.append(bbox)
        if self.error:raise self.error
        return self.payload

def make_service(tmp_path, client, azure=None):
    operations=OperationsRepository(tmp_path/"traffic.db")
    from app.services.trip_operations import BETIM_JABOATAO_ROUTE
    operations.upsert_route(BETIM_JABOATAO_ROUTE)
    with operations.connect() as connection:
        import json
        geometry=[{"latitude":lat,"longitude":lon} for lat,lon in ROUTE_GEOMETRIES["betim-jaboatao"]]
        connection.execute("INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,datetime('now'))",("betim-jaboatao","test-v1","test",json.dumps(geometry),"[]",300,"[]",1))
    return TrafficMonitoringService(TrafficRepository(operations),client,azure or FakeAzure())


def test_normalizes_provider_types_direction_and_audit_fields():
    accident=normalize_incident(raw_incident(icon=1),"betim-jaboatao",30)
    work=normalize_incident(raw_incident("work",icon=9),"betim-jaboatao",30)
    assert accident and accident["category"]=="ACIDENTE" and accident["severity"]=="CRITICO"
    assert accident["direction"]=="Norte" and accident["original_type"]=="1"
    assert work and work["category"]=="OBRA"


@pytest.mark.asyncio
async def test_collects_route_in_sections_deduplicates_overlap_and_filters_corridor(tmp_path,monkeypatch):
    inside=raw_incident(point=ROUTE_GEOMETRIES["betim-jaboatao"][1])
    outside=raw_incident("outside",point=(-25,-50))
    client=FakeClient({"incidents":[inside,inside,outside]});service=make_service(tmp_path,client)
    result=await service.collect([trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])])
    assert 1<len(client.boxes)<15
    assert result["incident_count"]==1
    assert len(service.repository.incidents("betim-jaboatao"))==1
    assert service.repository.latest_snapshot("betim-jaboatao")["request_count"]==len(client.boxes)
    assert service.azure_client.boxes==[]


@pytest.mark.asyncio
async def test_collects_multiple_active_persisted_routes_and_reports_missing_geometry(tmp_path):
    service=make_service(tmp_path,FakeClient())
    operations=service.repository.operations
    from app.services.trip_operations import BETIM_JABOATAO_ROUTE
    base={**BETIM_JABOATAO_ROUTE,"name":"Rota dois","active":True,"match_terms":[]}
    operations.upsert_route({**base,"id":"route-two"})
    operations.upsert_route({**base,"id":"route-missing","name":"Sem geometria"})
    import json
    geometry=[{"latitude":-23.0,"longitude":-46.0},{"latitude":-22.0,"longitude":-45.0}]
    with operations.connect() as connection:
        connection.execute("INSERT INTO route_geometry_versions(route_id,version,source,geometry_json,mandatory_points_json,corridor_m,segment_tolerances_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,datetime('now'))",("route-two","test-v1","test",json.dumps(geometry),"[]",300,"[]",1))
    route_two_trip={"plate":"TWO2","position":{"latitude":-23.0,"longitude":-46.0},"operational":{"trip_key":"trip:two","route_id":"route-two"}}
    result=await service.collect([route_two_trip])
    assert result["status"]=="OPERATIONAL"
    assert service.repository.latest_snapshot("route-two")["status"]=="OPERATIONAL"
    missing=service.repository.latest_snapshot("route-missing")
    assert missing["status"]=="DEGRADED" and missing["request_count"]==0


def test_bbox_segmentation_is_deduplicated_and_bounded():
    boxes=TrafficMonitoringService._query_boxes([(-20.0,-44.0),(-20.0,-44.0),(-19.0,-43.0)],60,15)
    assert len(boxes)==len(set(tuple(round(value,4) for value in box) for box in boxes))
    assert all(west<east and south<north for west,south,east,north in boxes)


def test_normalizes_orbis_descriptive_categories():
    works=raw_incident(icon="roadWorks"); closed=raw_incident("closed",icon="roadClosed")
    assert normalize_incident(works,"route",30)["category"]=="OBRA"
    assert normalize_incident(closed,"route",30)["category"]=="VIA_FECHADA"
    assert normalize_incident(raw_incident("accident",icon="accident"),"route",30)["category"]=="ACIDENTE"
    assert normalize_incident(raw_incident("jam",icon="jam"),"route",30)["category"]=="CONGESTIONAMENTO"


@pytest.mark.asyncio
async def test_insufficient_funds_uses_azure_fallback_without_repeated_tomtom_calls(tmp_path,monkeypatch):
    settings=__import__("app.core.config",fromlist=["get_settings"]).get_settings();monkeypatch.setattr(settings,"tomtom_api_key","configured");monkeypatch.setattr(settings,"azure_maps_subscription_key","configured")
    point=ROUTE_GEOMETRIES["betim-jaboatao"][1]
    azure=FakeAzure({"type":"FeatureCollection","features":[{"type":"Feature","id":"az-1","geometry":{"type":"Point","coordinates":[point[1],point[0]]},"properties":{"incidentType":"Construction","severity":2,"endTime":"2099-01-01T00:00:00Z"}}]})
    client=FakeClient(error=AuthError("blocked",403,"InsufficientFunds")); service=make_service(tmp_path,client,azure)
    active_trip=trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])
    first=await service.collect([active_trip])
    restarted=TrafficMonitoringService(service.repository,client,azure)
    second=await restarted.collect([active_trip])
    assert first["status"]==second["status"]=="OPERATIONAL"
    assert len(client.boxes)<=2 and azure.boxes
    health=service.repository.health()["tomtom_traffic_incidents"]
    assert health["status"]=="INSUFFICIENT_FUNDS"
    assert service.repository.health()["azure_maps_traffic_incidents"]["status"]=="OPERATIONAL"


@pytest.mark.asyncio
async def test_rate_limit_safely_falls_back_to_azure(tmp_path,monkeypatch):
    settings=__import__("app.core.config",fromlist=["get_settings"]).get_settings();monkeypatch.setattr(settings,"tomtom_api_key","configured");monkeypatch.setattr(settings,"azure_maps_subscription_key","configured")
    azure=FakeAzure();client=FakeClient(error=RateLimitError("limited")); service=make_service(tmp_path,client,azure)
    active_trip=trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])
    first=await service.collect([active_trip]); second=await service.collect([active_trip])
    assert first["status"]==second["status"]=="OPERATIONAL"
    assert len(client.boxes)<=2 and azure.boxes


def test_associates_only_events_ahead_on_route_without_double_counting_eta():
    route=ROUTE_GEOMETRIES["betim-jaboatao"]
    event=normalize_incident(raw_incident(point=route[2]),"betim-jaboatao",30)
    assert event
    affected=associate_incident(event,[trip(route[0])],route,15)
    assert affected and affected[0]["distance_along_route_km"]>0
    assert affected[0]["eta_adjustment_applied"] is False
    assert event["delay_already_in_eta"] is True
    behind=normalize_incident(raw_incident("behind",point=route[0]),"betim-jaboatao",30)
    assert behind and associate_incident(behind,[trip(route[3])],route,15)==[]
    off=normalize_incident(raw_incident("off",point=(-25,-50)),"betim-jaboatao",30)
    assert off and associate_incident(off,[trip(route[0])],route,15)==[]


def test_adaptive_corridor_precision_and_ahead_filter():
    route=[(0.0,0.0),(0.0,0.1)]
    vehicle={"plate":"TEST1","position":{"latitude":0.0,"longitude":0.01},"operational":{"trip_key":"trip:test"}}
    def event(latitude: float, longitude: float=0.05):
        return {"latitude":latitude,"longitude":longitude,"geometry":{"type":"Point","coordinates":[longitude,latitude]},"severity":"ATENCAO","delay_seconds":0}
    assert associate_incident(event(150/111_000),[vehicle],route,.5)
    assert associate_incident(event(400/111_000),[vehicle],route,.5)
    assert associate_incident(event(700/111_000),[vehicle],route,.5)==[]
    assert associate_incident(event(900/111_000),[vehicle],route,1.0)
    assert associate_incident(event(700/111_000),[vehicle],route,.5)==[]  # via paralela fora do corredor
    assert associate_incident(event(0.0,.005),[vehicle],route,.5)==[]


def test_remaining_route_starts_at_vehicle_progress():
    route=[(0.0,0.0),(0.0,.05),(0.0,.1)]
    progress,_=route_projection((0.0,.025),route)
    remaining=remaining_route(route,progress)
    assert abs(remaining[0][1]-.025)<1e-6
    assert remaining[-1]==route[-1]


def test_route_densification_and_projection_support_long_corridor():
    route=ROUTE_GEOMETRIES["betim-jaboatao"]; dense=densify(route,60)
    assert len(dense)>len(route)
    start,_=route_projection(route[0],route); end,lateral=route_projection(route[-1],route)
    assert start==0 and end>1500 and lateral<1


@pytest.mark.asyncio
async def test_temporary_failure_keeps_last_valid_snapshot_and_sanitizes_health(tmp_path,monkeypatch):
    monkeypatch.setattr(__import__("app.core.config",fromlist=["get_settings"]).get_settings(),"azure_maps_subscription_key","")
    on_route=raw_incident(point=ROUTE_GEOMETRIES["betim-jaboatao"][1])
    service=make_service(tmp_path,FakeClient({"incidents":[on_route]}))
    await service.collect([trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])])
    service._response_cache.clear()
    service.client=FakeClient(error=UnavailableError("secret-value-must-not-leak"))
    result=await service.collect([trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])])
    assert result["status"]=="ERROR"
    assert len(service.repository.incidents("betim-jaboatao"))==1
    health=str(service.repository.health())
    assert "secret-value-must-not-leak" not in health and "UnavailableError" in health


def test_expiration_and_persistence_after_restart(tmp_path):
    path=tmp_path/"traffic.db";service=make_service(tmp_path,FakeClient())
    incident=normalize_incident(raw_incident(end="2020-01-01T00:00:00Z"),"betim-jaboatao",30);assert incident
    service.repository.upsert_incident(incident);assert service.repository.expire()==1
    restarted=TrafficRepository(OperationsRepository(path))
    assert restarted.incidents("betim-jaboatao")==[]
    assert restarted.incident(incident["id"])["status"]=="EXPIRED"


def test_successful_cycle_expires_previously_persisted_off_corridor_incident(tmp_path):
    route=ROUTE_GEOMETRIES["betim-jaboatao"]
    service=make_service(tmp_path,FakeClient({"incidents":[raw_incident("kept",point=route[1])]}))
    stale=normalize_incident(raw_incident("stale",point=(-25,-50)),"betim-jaboatao",30)
    assert stale
    service.repository.upsert_incident(stale)
    result=__import__('asyncio').run(service.collect([trip(route[0])]))
    assert result["status"]=="OPERATIONAL"
    assert [item["id"] for item in service.repository.incidents("betim-jaboatao")]==["tomtom:kept"]
    assert service.repository.incident("tomtom:stale")["status"]=="EXPIRED"


def test_manual_create_edit_confirm_and_close_are_audited(tmp_path):
    service=make_service(tmp_path,FakeClient());now=datetime.now(timezone.utc)
    created=service.create_manual({"route_id":"betim-jaboatao","category":"OCORRENCIA_MANUAL","severity":"ATENCAO","description":"Fila informada pelo motorista","latitude":-19.9,"longitude":-44.2,"direction":"Norte","started_at":now.isoformat(),"expires_at":(now+timedelta(hours=2)).isoformat(),"information_source":"relato não verificado","responsible_user":"operador","justification":"Relato recebido por telefone","road_name":"BR-381"})
    assert created["manual"] and created["history"][0]["action"]=="CREATED"
    edited=service.repository.update_manual(created["id"],{"description":"Fila confirmada"},"EDITED","operador","Confirmação por segundo relato")
    assert edited["description"]=="Fila confirmada"
    closed=service.repository.update_manual(created["id"],{"status":"CLOSED"},"CLOSED","operador","Fluxo normalizado")
    assert closed["status"]=="CLOSED" and len(closed["history"])==3


def test_second_route_can_use_same_projection_and_association_logic(tmp_path):
    route=[(-23.0,-46.0),(-22.5,-45.5),(-22.0,-45.0)]
    event={"latitude":-22.5,"longitude":-45.5,"severity":"ATENCAO","delay_seconds":0}
    affected=associate_incident(event,[{"plate":"BBB2B22","position":{"latitude":-23.0,"longitude":-46.0},"operational":{"trip_key":"two"}}],route,15)
    assert affected and affected[0]["plate"]=="BBB2B22"
