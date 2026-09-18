import sqlite3

from app.services.driver_history import DriverHistoryService
from app.storage.migrations import migrate_database
from app.storage.operations import OperationsRepository


def seed(database):
    migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """INSERT INTO driver_profiles(
                id,cpf,name,phone,emergency_phone,client_operation,routes_json,
                vehicle_profile,identity_status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            [
                ("drv_a","32684773880","Ana Silva","(11) 99999-0001","(11) 98888-0002","SHOPEE",'["Betim - Jaboatão"]',"Truck","VERIFIED","2026-09-01","2026-09-01"),
                ("drv_b",None,"Bruno Souza","(31) 97777-0003",None,"LM2 RODAS",'[]',"Baú","PENDING","2026-09-02","2026-09-02"),
            ],
        )


def test_master_search_normalizes_cpf_and_phone(tmp_path):
    database=tmp_path/"operations.db";seed(database)
    service=DriverHistoryService(OperationsRepository(database))
    assert service.master_drivers(search="326.847.738-80")["items"][0]["id"]=="drv_a"
    assert service.master_drivers(search="11988880002")["items"][0]["id"]=="drv_a"


def test_history_search_accepts_formatted_cpf(tmp_path):
    database=tmp_path/"operations.db";seed(database)
    service=DriverHistoryService(OperationsRepository(database))
    result=service.drivers(search="326.847.738-80")
    assert result["total"]==1
    assert result["items"][0]["id"]=="drv_a"
    assert result["items"][0]["cpf_masked"]=="***.***.***-80"


def test_history_read_does_not_run_identity_consolidation(tmp_path, monkeypatch):
    database=tmp_path/"operations.db";seed(database)
    service=DriverHistoryService(OperationsRepository(database))
    monkeypatch.setattr(service,"consolidate_verified_identities",lambda: (_ for _ in ()).throw(AssertionError("read must not consolidate")))
    assert service.drivers()["total"]==2


def test_driver_report_includes_route_stops_and_communication_gaps(tmp_path, monkeypatch):
    database=tmp_path/"operations.db";seed(database)
    service=DriverHistoryService(OperationsRepository(database))
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO operational_trips(trip_key,plate,state,current_driver,created_at,updated_at) VALUES(?,?,?,?,?,?)",("trip_report","ABC1D23","EM_VIAGEM","Ana Silva","2026-09-10T10:00:00+00:00","2026-09-10T11:00:00+00:00"))
        connection.execute("INSERT INTO driver_trip_history(trip_key,driver_id,plate,status,source,source_updated_at,automatic_punctuality,closed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",("trip_report","drv_a","ABC1D23","EM_VIAGEM","test","2026-09-10T11:00:00+00:00","UNAVAILABLE",0,"2026-09-10T10:00:00+00:00","2026-09-10T11:00:00+00:00"))
    from app.services.trip_report import TripReportService
    monkeypatch.setattr(TripReportService,"evidence",lambda self,key:{
        "positions":[{"latitude":-23.0,"longitude":-46.0,"recorded_at":"2026-09-10T10:00:00+00:00"},{"latitude":-22.9,"longitude":-45.9,"recorded_at":"2026-09-10T11:00:00+00:00"}],
        "stops":[{"id":1,"started_at":"2026-09-10T10:10:00+00:00","ended_at":"2026-09-10T10:20:00+00:00","duration_minutes":10,"latitude":-22.95,"longitude":-45.95,"reason_text":None}],
        "communication_gaps":[{"started_at":"2026-09-10T10:30:00+00:00","ended_at":"2026-09-10T10:55:00+00:00","duration_minutes":25}],
        "summary":{"observed_stop_minutes":10},
    })
    html=service.report_html("drv_a",service.trips("drv_a",page_size=100)["items"])
    assert "Percurso registrado" in html and "2 posições GPS" in html
    assert "Paradas e pausas observadas" in html and "10 min" in html
    assert "Lacunas de comunicação" in html and "Ausência de sinal não é contabilizada como parada" in html


def test_report_correction_preserves_original_and_every_revision(tmp_path, monkeypatch):
    database=tmp_path/"operations.db";seed(database)
    service=DriverHistoryService(OperationsRepository(database))
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO operational_trips(trip_key,plate,state,current_driver,created_at,updated_at) VALUES(?,?,?,?,?,?)",("trip_edit","ABC1D23","EM_VIAGEM","Ana Silva","2026-09-10","2026-09-10"))
        connection.execute("INSERT INTO driver_trip_history(trip_key,driver_id,plate,status,started_at,source,source_updated_at,automatic_punctuality,closed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",("trip_edit","drv_a","ABC1D23","EM_VIAGEM","2026-09-10T08:00:00+00:00","test","2026-09-10","UNAVAILABLE",0,"2026-09-10","2026-09-10"))
    from app.services.trip_report import TripReportService
    monkeypatch.setattr(TripReportService,"evidence",lambda self,key:{"positions":[],"stops":[],"communication_gaps":[],"summary":{"observed_stop_minutes":0}})
    first=service.correct_report_field("trip_edit",field="trip.started_at",value="2026-09-10T08:20:00+00:00",justification="Correção confirmada pelo GR",responsible="Operador GR")
    second=service.correct_report_field("trip_edit",field="trip.started_at",value="2026-09-10T08:25:00+00:00",justification="Novo comprovante recebido",responsible="Administrador")
    field=next(item for item in second["fields"] if item["key"]=="trip.started_at")
    assert field["original"]=="2026-09-10T08:00:00+00:00"
    assert first["changes"][0]["previous_value"]=="2026-09-10T08:00:00+00:00"
    assert field["value"]=="2026-09-10T08:25:00+00:00" and len(field["history"])==2
    assert field["history"][1]["previous_value"]=="2026-09-10T08:20:00+00:00"


def test_consolidates_pending_profiles_only_with_one_verified_cpf_match(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO driver_profiles(id,name,identity_status,created_at,updated_at) VALUES('drv_pending','Ana Silva','PENDING','2026-09-02','2026-09-02')")
        connection.execute("INSERT INTO operational_trips(trip_key,plate,state,current_driver,created_at,updated_at) VALUES('trip_merge','ABC1D23','EM_VIAGEM','Ana Silva','2026-09-10','2026-09-10')")
        connection.execute("INSERT INTO driver_trip_history(trip_key,driver_id,plate,status,source,source_updated_at,automatic_punctuality,closed,created_at,updated_at) VALUES('trip_merge','drv_pending','ABC1D23','EM_VIAGEM','test','2026-09-10','UNAVAILABLE',0,'2026-09-10','2026-09-10')")
    assert service.consolidate_verified_identities()==1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT driver_id FROM driver_trip_history WHERE trip_key='trip_merge'").fetchone()[0]=="drv_a"
        assert connection.execute("SELECT COUNT(*) FROM driver_profiles WHERE id='drv_pending'").fetchone()[0]==0


def test_master_filters_and_paginates_persistent_profiles(tmp_path):
    database=tmp_path/"operations.db";seed(database)
    service=DriverHistoryService(OperationsRepository(database))
    result=service.master_drivers(client_operation="SHOPEE",vehicle_profile="Truck",route="Betim - Jaboatão",page=1,page_size=1)
    assert result["total"]==1
    assert result["items"][0]["routes"]==["Betim - Jaboatão"]
    assert "SHOPEE" in result["facets"]["client_operations"]
    assert result["page_size"]==1


def test_normalized_cpf_unique_constraint_prevents_duplicate(tmp_path):
    database=tmp_path/"operations.db";seed(database)
    with sqlite3.connect(database) as connection:
        try:
            connection.execute("INSERT INTO driver_profiles(id,cpf,name,identity_status,created_at,updated_at) VALUES('drv_duplicate','32684773880','Duplicada','VERIFIED','2026-09-03','2026-09-03')")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("CPF normalizado duplicado deveria ser bloqueado")

def test_import_updates_by_cpf_preserving_id_and_non_blank_values(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    rows=[{"source_row":2,"name":"Ana Atualizada","cpf":"326.847.738-80","primary_phone":"","emergency_phone":"","status":"ATIVO","registration_date":"2026-09-10","client_operation":"CEVA","routes":["SP - MG"],"vehicle_profile":"","warnings":[]}]
    preview=service.preview_master_import(file_name="motoristas.xlsx",rows=rows)
    assert preview["update_count"]==1 and preview["items"][0]["cpf_masked"]=="***.***.***-80"
    result=service.import_master(file_name="motoristas.xlsx",rows=rows)
    assert result["updated"]==1
    with sqlite3.connect(database) as connection:
        saved=connection.execute("SELECT id,name,phone,emergency_phone FROM driver_profiles WHERE cpf='32684773880'").fetchone()
    assert saved==("drv_a","Ana Atualizada","(11) 99999-0001","(11) 98888-0002")

def test_import_never_merges_missing_cpf_by_name(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    rows=[{"source_row":2,"name":"Ana Silva","cpf":"","routes":[],"warnings":["CPF não informado"]}]
    preview=service.preview_master_import(file_name="motoristas.csv",rows=rows)
    assert preview["pending_count"]==1 and preview["items"][0]["importable"] is False
    result=service.import_master(file_name="motoristas.csv",rows=rows)
    assert result["created"]==0 and result["ignored"]==1

def test_same_name_with_different_cpf_creates_distinct_driver(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    rows=[{"source_row":2,"name":"Ana Silva","cpf":"11122233344","routes":[],"warnings":[]}]
    result=service.import_master(file_name="motoristas.csv",rows=rows)
    assert result["created"]==1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM driver_profiles WHERE name='Ana Silva'").fetchone()[0]==2

def test_preview_cancel_does_not_write_and_refresh_keeps_confirmed_data(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    rows=[{"source_row":2,"name":"Carlos Lima","cpf":"55566677788","routes":[],"warnings":[]}]
    service.preview_master_import(file_name="motoristas.xlsx",rows=rows)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM driver_profiles WHERE cpf='55566677788'").fetchone()[0]==0
    service.import_master(file_name="motoristas.xlsx",rows=rows)
    refreshed=DriverHistoryService(OperationsRepository(database)).master_drivers(search="55566677788")
    assert refreshed["total"]==1 and refreshed["items"][0]["name"]=="Carlos Lima"

def test_import_preserves_driver_history_relationship(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO driver_trip_history(trip_key,driver_id,plate,status,source,source_updated_at,automatic_punctuality,closed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",("trip_a","drv_a","FQS9C14","ATIVA","test","2026-09-01","UNAVAILABLE",0,"2026-09-01","2026-09-01"))
    service.import_master(file_name="motoristas.csv",rows=[{"source_row":2,"name":"Ana Nova","cpf":"32684773880","routes":[],"warnings":[]}])
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT driver_id FROM driver_trip_history WHERE trip_key='trip_a'").fetchone()[0]=="drv_a"

def test_critical_write_error_rolls_back_entire_import(tmp_path):
    database=tmp_path/"operations.db";seed(database);service=DriverHistoryService(OperationsRepository(database))
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TRIGGER fail_second_driver BEFORE INSERT ON driver_profiles WHEN NEW.cpf='99988877766' BEGIN SELECT RAISE(ABORT,'forced failure'); END")
    rows=[{"source_row":2,"name":"Primeiro","cpf":"11133355577","routes":[],"warnings":[]},{"source_row":3,"name":"Segundo","cpf":"99988877766","routes":[],"warnings":[]}]
    try: service.import_master(file_name="motoristas.csv",rows=rows)
    except sqlite3.IntegrityError: pass
    else: raise AssertionError("A falha crítica deveria interromper a transação")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM driver_profiles WHERE cpf IN ('11133355577','99988877766')").fetchone()[0]==0
