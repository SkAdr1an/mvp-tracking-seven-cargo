from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Configure a disposable database before importing application singletons.
TEST_DATABASE_ROOT = Path(tempfile.mkdtemp(prefix="seven-cargo-tests-"))
os.environ["OPERATIONS_DATABASE_PATH"] = str(TEST_DATABASE_ROOT / "operations.db")
os.environ["FLEET_COLLECTOR_ENABLED"] = "false"
os.environ["TRAFFIC_COLLECTOR_ENABLED"] = "false"
os.environ["OPERATIONS_BACKUP_ENABLED"] = "false"

import pytest

from app.core.security import Permission, Principal, Role, require_permission
from app.main import app
from app.storage.angellira import AngelLiraRepository
from app.storage.migrations import migrate_database
from app.storage.operations import OperationsRepository
from app.services.operational_sites import OperationalSiteService


@pytest.fixture(autouse=True)
def explicitly_migrated_test_repositories(monkeypatch, request):
    """Legacy unit tests get an explicit disposable migration before repository use.

    Production constructors remain side-effect free; this adapter is test-only.
    """
    if request.node.get_closest_marker("runtime_schema_invariance"):
        yield
        return

    operations_init = OperationsRepository.__init__
    angellira_init = AngelLiraRepository.__init__
    sites_init = OperationalSiteService.__init__

    def initialize_operations(self, database_path):
        if str(database_path) != ":memory:":
            migrate_database(database_path)
        operations_init(self, database_path)

    def initialize_angellira(self, database_path):
        if str(database_path) != ":memory:":
            migrate_database(database_path)
        angellira_init(self, database_path)

    def initialize_sites(self, database_path):
        migrate_database(database_path)
        sites_init(self, database_path)

    monkeypatch.setattr(OperationsRepository, "__init__", initialize_operations)
    monkeypatch.setattr(AngelLiraRepository, "__init__", initialize_angellira)
    monkeypatch.setattr(OperationalSiteService, "__init__", initialize_sites)
    yield


@pytest.fixture(autouse=True)
def isolate_import_time_operational_singletons(tmp_path, monkeypatch, request):
    """Keep import-time services on a disposable database for every test.

    Several legacy services intentionally share process-wide caches. Merely
    monkeypatching Settings does not update repositories captured at import.
    """
    if request.node.get_closest_marker("runtime_schema_invariance"):
        yield
        return

    from app.api import operations as operations_api, public_trip as public_trip_api
    from app.core.config import get_settings
    from app.services import fleet_tracking, route_deviation, route_progress, traffic_monitoring
    from app.services.operational_diagnostic import OperationalDiagnosticService
    from app.services.public_trip import PublicTripService
    from app.services.return_tracking import ReturnTrackingService
    from app.services.trip_operations import trip_operations_service

    database = tmp_path / "singleton-runtime.sqlite"
    migrate_database(database)
    repository = OperationsRepository(database)
    monkeypatch.setattr(get_settings(), "operations_database_path", database)

    monkeypatch.setattr(trip_operations_service, "repository", repository)
    monkeypatch.setattr(trip_operations_service, "return_tracking", ReturnTrackingService(repository))
    monkeypatch.setattr(operations_api, "trip_operations_service", trip_operations_service)
    monkeypatch.setattr(route_deviation.route_deviation_service, "repository", repository)
    monkeypatch.setattr(route_progress.route_progress_service, "repository", repository)
    monkeypatch.setattr(fleet_tracking.fleet_tracking_service, "diagnostics",
                        OperationalDiagnosticService(repository))
    monkeypatch.setattr(traffic_monitoring.traffic_repository, "operations", repository)
    monkeypatch.setattr(public_trip_api, "public_trip_service", PublicTripService(repository))
    yield


@pytest.fixture(autouse=True)
def authenticated_functional_tests():
    """Existing functional tests exercise business behavior as an admin.

    Dedicated security tests remove these overrides to assert the real 401/403
    boundary. This keeps provider mocks focused and prevents external calls.
    """
    principal = Principal("functional-test-admin", Role.ADMIN)
    dependencies = [
        require_permission(Permission.OPERATIONAL_READ),
        require_permission(Permission.DASHBOARD_READ),
        require_permission(Permission.INTEGRATIONS_INVOKE),
    ]
    for dependency in dependencies:
        app.dependency_overrides[dependency] = lambda principal=principal: principal
    yield
    for dependency in dependencies:
        app.dependency_overrides.pop(dependency, None)
