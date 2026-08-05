from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.tomtom import UnavailableError
from app.services.traffic_monitoring import (
    ROUTE_GEOMETRIES, TrafficMonitoringService, associate_incident, densify,
    normalize_incident, route_projection,
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


def make_service(tmp_path, client):
    operations=OperationsRepository(tmp_path/"traffic.db")
    from app.services.trip_operations import BETIM_JABOATAO_ROUTE
    operations.upsert_route(BETIM_JABOATAO_ROUTE)
    return TrafficMonitoringService(TrafficRepository(operations),client)


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


def test_route_densification_and_projection_support_long_corridor():
    route=ROUTE_GEOMETRIES["betim-jaboatao"]; dense=densify(route,60)
    assert len(dense)>len(route)
    start,_=route_projection(route[0],route); end,lateral=route_projection(route[-1],route)
    assert start==0 and end>1500 and lateral<1


@pytest.mark.asyncio
async def test_temporary_failure_keeps_last_valid_snapshot_and_sanitizes_health(tmp_path):
    service=make_service(tmp_path,FakeClient({"incidents":[raw_incident()]}))
    await service.collect([trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])])
    service.client=FakeClient(error=UnavailableError("secret-value-must-not-leak"))
    result=await service.collect([trip(ROUTE_GEOMETRIES["betim-jaboatao"][0])])
    assert result["status"]=="DEGRADED"
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
