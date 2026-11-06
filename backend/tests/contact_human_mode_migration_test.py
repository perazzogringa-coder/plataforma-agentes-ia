"""Focused contract checks; PostgreSQL integration is run separately."""
import importlib.util
import io
import os
from pathlib import Path
import subprocess

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_migration_only_changes_server_default(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0002_contacts_human_mode_default.py"
    spec = importlib.util.spec_from_file_location("human_mode_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    calls = []
    monkeypatch.setattr(migration.op, "alter_column", lambda *a, **kw: calls.append((a, kw)))

    migration.upgrade()
    migration.downgrade()

    assert migration.down_revision == "0001"
    assert [call[0] for call in calls] == [("contacts", "human_mode")] * 2
    assert str(calls[0][1]["server_default"]) == "false"
    assert calls[1][1]["server_default"] is None
    assert all(call[1]["existing_nullable"] is False for call in calls)


def test_postgres_preserves_existing_values_and_downgrades():
    container = os.getenv("CODEX_ISOLATED_PG_CONTAINER")
    if container != "codex-humanmode-pg-20261020":
        pytest.skip("Requires the dedicated network-isolated test container")
    spec = importlib.util.spec_from_file_location(
        "human_mode_migration_pg",
        Path(__file__).parents[1] / "alembic/versions/0002_contacts_human_mode_default.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    sql = []
    for operation in (migration.upgrade, migration.downgrade):
        buf = io.StringIO()
        context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buf})
        with Operations.context(context):
            operation()
        sql.append(buf.getvalue())
    script = """
    CREATE TABLE contacts (id integer primary key, human_mode boolean NOT NULL);
    INSERT INTO contacts VALUES (1, true), (2, false);
    """ + sql[0] + """
    INSERT INTO contacts (id) VALUES (3);
    SELECT string_agg(id::text || ':' || human_mode::text, ',' ORDER BY id) FROM contacts;
    """ + sql[1] + """
    SELECT column_default IS NULL FROM information_schema.columns
      WHERE table_name = 'contacts' AND column_name = 'human_mode';
    SELECT string_agg(id::text || ':' || human_mode::text, ',' ORDER BY id) FROM contacts;
    """
    run = subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "postgres", "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1"],
        input=script, text=True, capture_output=True, check=True, timeout=20,
    )
    assert run.stdout.splitlines() == ["1:true,2:false,3:false", "t", "1:true,2:false,3:false"]
