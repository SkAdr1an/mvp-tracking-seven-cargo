from app.core.security import Principal, Role
from app.services.audit import AuditAction, AuditService
from app.storage.migrations import migrate_database


def service(tmp_path):
    database = tmp_path / "audit.db"
    migrate_database(database)
    return AuditService(database)


def test_actor_query_searches_human_name_and_username(tmp_path):
    audit = service(tmp_path)
    anthony = Principal("anthony", Role.MONITORING, display_name="Anthony")
    other = Principal("nicolas", Role.GR, display_name="Nicolas Dias")
    audit.record(anthony, AuditAction.AUTH_LOGIN_SUCCESS, "authentication")
    audit.record(other, AuditAction.AUTH_LOGIN_SUCCESS, "authentication")
    result = audit.query(actor_query="  ANTHONY ", action_type="AUTH_LOGIN_SUCCESS")
    assert [event["actor_display_name_snapshot"] for event in result["events"]] == ["Anthony"]


def test_cursor_paginates_by_timestamp_and_id_without_duplicates(tmp_path):
    audit = service(tmp_path)
    actor = Principal("auditor", Role.ADMIN, display_name="Auditor")
    for number in range(31):
        audit.record(actor, AuditAction.REPORT_GENERATED, "report", resource_id=number)
    first = audit.query(limit=10)
    second = audit.query(limit=10, cursor=first["next_cursor"])
    third = audit.query(limit=20, cursor=second["next_cursor"])
    identifiers = [event["id"] for page in (first, second, third) for event in page["events"]]
    assert len(identifiers) == 31
    assert len(set(identifiers)) == 31
