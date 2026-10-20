from importlib import import_module


def test_migration_runner_is_numbered_and_ordered():
    migrations = import_module('01_HCM.db_migrations')
    versions = [int(path.name[:3]) for path in migrations.MIGRATIONS]

    assert versions == sorted(versions)
    assert versions == list(range(1, 20))
