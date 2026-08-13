from __future__ import annotations

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
