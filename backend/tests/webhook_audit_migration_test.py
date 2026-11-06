"""PostgreSQL-only tests against a disposable, network-isolated container."""
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory


CONTAINER = "codex-audit-pg-20261020"
ROOT = Path(__file__).parents[1] / "alembic/versions"


def test_alembic_revision_chain():
    config = Config()
    config.set_main_option("script_location", str(ROOT.parent))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0005_contacts_company_identity"]
    assert [revision.revision for revision in script.walk_revisions()] == [
        "0005_contacts_company_identity", "0004_contacts_waha_fields", "0003_webhook_audit", "0002_contacts_human_mode_default", "0001"
    ]


def migration(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rendered(function):
    out = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": out})
    with Operations.context(context):
        function()
    return out.getvalue()


def psql(sql, check=True):
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", "postgres", "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, timeout=25, check=check,
    )


@pytest.fixture(scope="module")
def isolated_postgres():
    if os.getenv("CODEX_ISOLATED_PG_CONTAINER") != CONTAINER:
        pytest.skip("Requires dedicated test container")
    inspect = subprocess.run(["docker", "inspect", "--format", "{{.HostConfig.NetworkMode}}", CONTAINER], text=True, capture_output=True, check=True, timeout=5)
    if inspect.stdout.strip() != "none":
        pytest.fail("Refusing a PostgreSQL container without network isolation")
    for _ in range(30):
        logs = subprocess.run(["docker", "logs", CONTAINER], capture_output=True, timeout=3)
        ready = subprocess.run(["docker", "exec", CONTAINER, "pg_isready", "-U", "postgres"], capture_output=True, timeout=3)
        if b"PostgreSQL init process complete" in logs.stdout and ready.returncode == 0:
            break
        time.sleep(0.5)
    else:
        pytest.fail("Isolated PostgreSQL did not become ready")
    first = migration("0002_contacts_human_mode_default")
    second = migration("0003_webhook_audit")
    assert first.down_revision == "0001"
    assert second.down_revision == first.revision
    psql("CREATE TABLE contacts (id integer primary key, human_mode boolean NOT NULL);" + rendered(first.upgrade) + rendered(second.upgrade))


def test_real_consumer_sql_and_statuses(isolated_postgres):
    result = psql("""
        INSERT INTO webhook_audit
          (instance_id, company_id, message_id, phone, message_type, message_data, status)
        VALUES ('synthetic', 7, 'synthetic-message', '', 'waha:message', '{"synthetic":true}', 'received');
        UPDATE webhook_audit SET status='queued', updated_at=NOW(), task_id='synthetic-task' WHERE company_id=7;
        UPDATE webhook_audit SET status='processing', updated_at=NOW() WHERE company_id=7;
        UPDATE webhook_audit SET status='failed', updated_at=NOW(), error_message='synthetic', retry_count=retry_count+1 WHERE company_id=7;
        UPDATE webhook_audit SET processing_status='processing_failed', error_message='synthetic', updated_at=NOW() WHERE company_id=7;
        SELECT processing_status FROM webhook_audit WHERE company_id=7;
        SELECT count(*) FROM webhook_audit WHERE company_id=7 AND message_id='synthetic-message' AND message_type='waha:message' AND status <> 'queue_failed' AND created_at > NOW() - INTERVAL '5 minutes';
        UPDATE webhook_audit SET status='queue_failed', updated_at=NOW(), retry_count=retry_count+1 WHERE company_id=7;
        SELECT status || ':' || retry_count::text FROM webhook_audit WHERE company_id=7;
        SELECT count(*) FROM webhook_audit WHERE company_id=7 AND message_id='synthetic-message' AND message_type='waha:message' AND status <> 'queue_failed' AND created_at > NOW() - INTERVAL '5 minutes';
        UPDATE webhook_audit SET status='completed', updated_at=NOW(), processed_at=NOW() WHERE company_id=7;
        SELECT count(*) FROM webhook_audit WHERE company_id=7 AND message_id='synthetic-message' AND message_type='waha:message' AND status <> 'queue_failed' AND created_at > NOW() - INTERVAL '5 minutes';
        SELECT count(*), (AVG(EXTRACT(EPOCH FROM (processed_at-created_at))) IS NOT NULL) FROM webhook_audit WHERE status='completed';
    """)
    assert result.stdout.splitlines() == ["processing_failed", "1", "queue_failed:2", "0", "1", "1|t"]


def test_deduplication_lock_with_concurrent_transactions(isolated_postgres):
    # Same advisory lock and lookup as the webhook; the first transaction
    # commits a received record before the second can query it.
    sql = """BEGIN;
        SELECT pg_advisory_xact_lock(hashtextextended('waha:8:message:synthetic', 0));
        SELECT pg_sleep(0.3);
        INSERT INTO webhook_audit (instance_id, company_id, message_id, message_type, status)
        SELECT 'synthetic', 8, 'synthetic', 'waha:message', 'received'
        WHERE NOT EXISTS (SELECT 1 FROM webhook_audit WHERE company_id=8 AND message_id='synthetic' AND message_type='waha:message' AND status <> 'queue_failed' AND created_at > NOW()-INTERVAL '5 minutes');
        COMMIT;"""
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(psql, [sql, sql]))
    assert all(r.returncode == 0 for r in results)
    assert psql("SELECT count(*) FROM webhook_audit WHERE company_id=8;").stdout.strip() == "1"
    assert psql("SELECT count(*) FROM webhook_audit WHERE company_id=9 OR message_type='waha:message.any';").stdout.strip() == "0"


def test_downgrade_refuses_to_destroy_audit_records(isolated_postgres):
    result = psql(rendered(migration("0003_webhook_audit").downgrade), check=False)
    assert result.returncode != 0
    assert "not empty" in result.stderr
    assert psql("SELECT count(*) FROM webhook_audit;").stdout.strip() == "2"


def test_empty_table_downgrade_is_reversible_within_transaction(isolated_postgres):
    sql = "BEGIN; DELETE FROM webhook_audit;" + rendered(migration("0003_webhook_audit").downgrade)
    sql += "SELECT to_regclass('webhook_audit') IS NULL; ROLLBACK; SELECT count(*) FROM webhook_audit;"
    assert psql(sql).stdout.splitlines() == ["t", "2"]
