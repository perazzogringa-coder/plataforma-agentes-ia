"""Synthetic webhook/worker integration; never use a production database."""
import asyncio
import os
import socket
import subprocess
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError


def test_webhook_to_worker_against_isolated_schema(monkeypatch, caplog):
    url = os.environ.get("DATABASE_URL", "")
    parsed = urlsplit(url)
    if os.environ.get("CODEX_INTEGRATION_CONTAINER") != "codex-integration-pg-20261020" or parsed.hostname != "127.0.0.1" or parsed.port in (None, 5432):
        pytest.skip("Requires a dedicated local synthetic PostgreSQL")
    binding = subprocess.run(["docker", "port", "codex-integration-pg-20261020", "5432/tcp"], capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    if binding != f"127.0.0.1:{parsed.port}" or not parsed.path.lstrip("/").startswith("synthetic"):
        pytest.fail("Refusing a database outside the disposable test container")

    # Deny all socket connections other than this disposable PostgreSQL.
    connect = socket.socket.connect
    def isolated_connect(sock, address):
        if not (isinstance(address, tuple) and address[0] == "127.0.0.1" and address[1] == parsed.port):
            raise AssertionError("External networking forbidden in integration test")
        return connect(sock, address)
    monkeypatch.setattr(socket.socket, "connect", isolated_connect)

    from backend.routes import waha_routes
    from backend.worker import process_message_waha as worker
    from backend.worker import process_message as shared
    from backend.services import flow_executor_waha as flow
    from backend.integrations import waha_utils
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    queued = []
    simulated = []
    try:
        db.execute(text("INSERT INTO companies (id, name, cnpj, name_company, waha_enabled, waha_session_name, operational_status) VALUES (9001, 'synthetic', '00000000000000', 'synthetic', true, 'synthetic', 'active')"))
        db.execute(text("INSERT INTO clients (id, company_id, ownership_company_id, is_active) VALUES (9001, 9001, 9001, true)"))
        db.execute(text("INSERT INTO client_companies (client_id, company_id) VALUES (9001, 9001)"))
        db.commit()
        monkeypatch.setattr(worker.process_incoming_waha_message, "apply_async", lambda args, queue: queued.append(args[0]) or SimpleNamespace(id="synthetic-task"))
        async def payload():
            return {"event": "message", "session": "synthetic", "payload": {"id": "synthetic-id", "from": "5500000000000@c.us", "fromMe": False, "type": "chat", "body": "synthetic"}}
        request = SimpleNamespace(json=payload)
        first = asyncio.run(waha_routes.waha_message_webhook(request, db))
        second = asyncio.run(waha_routes.waha_message_webhook(request, db))
        assert first["status"] == "queued"
        assert second["status"] == "duplicate"
        assert len(queued) == 1
        assert db.execute(text("SELECT status FROM webhook_audit WHERE company_id=9001")).scalar() == "queued"

        # Run the real worker against the synthetic database, forbidding network.
        monkeypatch.setattr(worker, "SessionLocal", Session)
        monkeypatch.setattr(worker, "append_message_to_chat_file", lambda *a, **kw: None)
        monkeypatch.setattr(shared, "publish_to_redis", lambda *a, **kw: None)
        monkeypatch.setattr(waha_utils, "persist_contact_profile_picture_as_webp", lambda **kw: None)
        monkeypatch.setattr(flow, "get_active_whatsapp_agent_workforce_context", lambda *a: None)
        monkeypatch.setattr(flow, "execute_flow_message", lambda *a: simulated.append(True) or {"success": True, "execution_log": []})
        try:
            worker.process_incoming_waha_message.run(queued[0])
        except Exception:
            pass  # The incompatible schema causes the task's retry path.
        db.expire_all()
        audit = db.execute(text("SELECT status, error_message FROM webhook_audit WHERE company_id=9001")).one()
        if os.environ.get("CODEX_EXPECT_WAHA_FIELDS") == "1":
            assert audit.status == "completed", (audit.status, audit.error_message)
            assert len(simulated) == 1
            assert db.execute(text("SELECT count(*) FROM contacts WHERE company_id=9001 AND unread_count=1")).scalar() == 1
            assert db.execute(text("SELECT count(*) FROM messages WHERE company_id=9001")).scalar() == 1
            worker.process_incoming_waha_message.run(queued[0])
            assert len(simulated) == 1
            first_unread = db.execute(text("SELECT unread_count FROM contacts WHERE client_id=9001 AND company_id=9001")).scalar()
            # Same phone can exist in separate companies for the same client.
            db.execute(text("INSERT INTO companies (id, name, cnpj, name_company, waha_enabled, waha_session_name, operational_status) VALUES (9002, 'synthetic', '00000000000001', 'synthetic', true, 'synthetic2', 'active')"))
            db.execute(text("INSERT INTO clients (id, company_id, ownership_company_id) VALUES (9002, 9002, 9002)"))
            db.execute(text("INSERT INTO client_companies (client_id,company_id) VALUES (9001,9002)"))
            db.execute(text("INSERT INTO contacts (client_id, company_id, phone) SELECT client_id, 9002, phone FROM contacts WHERE company_id=9001"))
            with pytest.raises(IntegrityError):
                with db.begin_nested():
                    db.execute(text("INSERT INTO contacts (client_id, company_id, phone) SELECT client_id, company_id, phone FROM contacts WHERE company_id=9001"))
            db.execute(text("INSERT INTO contacts (client_id, company_id, phone) SELECT 9002, 9002, phone FROM contacts WHERE company_id=9001"))
            assert db.execute(text("SELECT count(*) FROM contacts WHERE company_id IN (9001,9002)")).scalar() == 3
            db.execute(text("INSERT INTO contacts (client_id,company_id,phone) SELECT client_id,company_id,phone FROM contacts WHERE company_id=9001 ON CONFLICT (client_id,company_id,phone) DO NOTHING"))
            db.commit()
            async def payload2():
                return {"event": "message", "session": "synthetic2", "payload": {"id": "synthetic-id-2", "from": "5500000000000@c.us", "fromMe": False, "type": "chat", "body": "synthetic"}}
            assert asyncio.run(waha_routes.waha_message_webhook(SimpleNamespace(json=payload2), db))["status"] == "queued"
            worker.process_incoming_waha_message.run(queued[-1])
            counts = db.execute(text("SELECT company_id, unread_count FROM contacts WHERE client_id=9001 ORDER BY company_id")).all()
            assert counts == [(9001, first_unread), (9002, 1)]
            assert len(simulated) == 2
            from fastapi import HTTPException
            from backend.routes.contact_notes import get_contact_notes
            from backend.routes.contact_tasks import get_contact_tasks
            user = SimpleNamespace(company_id=9002)
            for endpoint in (get_contact_notes, get_contact_tasks):
                with pytest.raises(HTTPException) as exc:
                    asyncio.run(endpoint("5500000000000", user=user, db=db))
                assert exc.value.status_code == 409

            # A failure after the message commit but before automation must not
            # turn a Celery retry into a false completed/duplicate result.
            async def payload3():
                return {"event": "message", "session": "synthetic", "payload": {"id": "synthetic-retry-after-persist", "from": "5500000000001@c.us", "fromMe": False, "type": "chat", "body": "synthetic"}}
            assert asyncio.run(waha_routes.waha_message_webhook(SimpleNamespace(json=payload3), db))["status"] == "queued"
            retry_task = queued[-1]
            def fail_publish(*args, **kwargs):
                raise RuntimeError("synthetic publish failure")
            monkeypatch.setattr(shared, "publish_to_redis", fail_publish)
            with pytest.raises(Exception):
                worker.process_incoming_waha_message.run(retry_task)
            db.expire_all()
            assert db.execute(text("SELECT status FROM webhook_audit WHERE id=:id"), {"id": retry_task["audit_id"]}).scalar() == "failed"
            assert db.execute(text("SELECT count(*) FROM messages WHERE zapi_message_id='synthetic-retry-after-persist'")).scalar() == 1
            monkeypatch.setattr(shared, "publish_to_redis", lambda *a, **kw: None)
            worker.process_incoming_waha_message.run(retry_task)
            db.expire_all()
            unread_after_retry = db.execute(text("SELECT unread_count FROM contacts WHERE client_id=9001 AND company_id=9001 AND phone='5500000000001'")).scalar()
            audit_after_retry = db.execute(text("SELECT status FROM webhook_audit WHERE id=:id"), {"id": retry_task["audit_id"]}).scalar()
            assert unread_after_retry == 1, "retry incremented unread_count twice"
            assert audit_after_retry != "completed" or len(simulated) == 3, "retry falsely marked the unprocessed automation completed"
            assert len(simulated) == 3, "retry after persistence skipped automation"

            # The downstream call may have sent before raising: never send again.
            async def payload4():
                return {"event": "message", "session": "synthetic", "payload": {"id": "synthetic-uncertain", "from": "5500000000002@c.us", "fromMe": False, "type": "chat", "body": "synthetic"}}
            assert asyncio.run(waha_routes.waha_message_webhook(SimpleNamespace(json=payload4), db))["status"] == "queued"
            uncertain_task = queued[-1]
            sends = []
            def send_then_fail(*args):
                sends.append(True)
                raise RuntimeError("synthetic ambiguous send")
            monkeypatch.setattr(flow, "execute_flow_message", send_then_fail)
            worker.process_incoming_waha_message.run(uncertain_task)
            db.expire_all()
            assert db.execute(text("SELECT status FROM webhook_audit WHERE id=:id"), {"id": uncertain_task["audit_id"]}).scalar() == "uncertain"
            worker.process_incoming_waha_message.run(uncertain_task)
            assert len(sends) == 1

            async def payload5():
                return {"event": "message", "session": "synthetic", "payload": {"id": "synthetic-concurrent", "from": "5500000000003@c.us", "fromMe": False, "type": "chat", "body": "synthetic"}}
            assert asyncio.run(waha_routes.waha_message_webhook(SimpleNamespace(json=payload5), db))["status"] == "queued"
            concurrent_task = queued[-1]
            key = f"waha-audit:9001:{concurrent_task['audit_id']}"
            with engine.connect() as lock:
                assert lock.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key}).scalar()
                try:
                    with pytest.raises(Exception):
                        worker.process_incoming_waha_message.run(concurrent_task)
                    db.expire_all()
                    assert db.execute(text("SELECT status FROM webhook_audit WHERE id=:id"), {"id": concurrent_task["audit_id"]}).scalar() == "queued"
                finally:
                    lock.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
            return
        assert "last_message_at" in caplog.text
        assert audit.status == "failed"
        assert "last_message_at" in (audit.error_message or "")
        assert asyncio.run(waha_routes.waha_message_webhook(request, db))["status"] == "duplicate"
        try:
            worker.process_incoming_waha_message.run(queued[0])
        except Exception:
            pass
        assert db.execute(text("SELECT retry_count FROM webhook_audit WHERE company_id=9001")).scalar() == 2
        assert db.execute(text("SELECT count(*) FROM messages WHERE company_id=9001")).scalar() == 0
    finally:
        db.close()
        engine.dispose()
