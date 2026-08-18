from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.storage.feature_migrations import OPERATIONAL_DATABASE, apply_migration_009, migration_009_pending, rollback_migration_009
from app.storage.operations import OperationsRepository


pytestmark = pytest.mark.runtime_schema_invariance


def test_test_environment_uses_disposable_database():
    from app.core.config import get_settings
    assert get_settings().operations_database_path != OPERATIONAL_DATABASE
    assert "seven-cargo-tests-" in str(get_settings().operations_database_path)


def test_repository_refuses_operational_path_under_pytest():
    assert "pytest" in sys.modules
    with pytest.raises(RuntimeError, match="Tests cannot use"):
        OperationsRepository(OPERATIONAL_DATABASE)


def test_feature_migration_requires_disposable_database(tmp_path: Path):
    repository = OperationsRepository(tmp_path / "migration.sqlite")
    assert migration_009_pending(repository.database_path)
    with pytest.raises(RuntimeError, match="explicitly disposable"):
        apply_migration_009(repository.database_path)
    with pytest.raises(RuntimeError, match="explicitly disposable"):
        apply_migration_009(OPERATIONAL_DATABASE, disposable=True)
    apply_migration_009(repository.database_path, disposable=True)
    assert not migration_009_pending(repository.database_path)
    rollback_migration_009(repository.database_path, disposable=True)
    assert migration_009_pending(repository.database_path)
