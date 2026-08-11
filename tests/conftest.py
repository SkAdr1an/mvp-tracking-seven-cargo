from __future__ import annotations

import pytest

from app.core.security import Permission, Principal, Role, require_permission
from app.main import app


@pytest.fixture(autouse=True)
def authenticated_functional_tests():
    """Existing functional tests exercise business behavior as an admin.

    Dedicated security tests remove these overrides to assert the real 401/403
    boundary. This keeps provider mocks focused and prevents external calls.
    """
    principal = Principal("functional-test-admin", Role.ADMIN)
    dependencies = [
        require_permission(Permission.OPERATIONAL_READ),
        require_permission(Permission.INTEGRATIONS_INVOKE),
    ]
    for dependency in dependencies:
        app.dependency_overrides[dependency] = lambda principal=principal: principal
    yield
    for dependency in dependencies:
        app.dependency_overrides.pop(dependency, None)
