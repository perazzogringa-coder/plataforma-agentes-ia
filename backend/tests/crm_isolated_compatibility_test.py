"""Contact-list compatibility using only the dedicated synthetic PostgreSQL."""
import os
import subprocess
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def test_contact_list_with_missing_optional_flow_tables():
    parsed = urlsplit(os.environ.get("DATABASE_URL", ""))
    if os.environ.get("CODEX_INTEGRATION_CONTAINER") != "codex-integration-pg-20261020" or parsed.hostname != "127.0.0.1" or parsed.port in (None, 5432) or not parsed.path.lstrip("/").startswith("synthetic"):
        pytest.skip("Dedicated synthetic PostgreSQL required")
    binding = subprocess.run(["docker", "port", "codex-integration-pg-20261020", "5432/tcp"], capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    assert binding == f"127.0.0.1:{parsed.port}"
    from fastapi import HTTPException
    from backend.models import Client
    from backend.routes.webhook import get_contacts

    engine = create_engine(os.environ["DATABASE_URL"])
    db = sessionmaker(bind=engine)()
    try:
        db.execute(text("INSERT INTO companies (id,name,cnpj,name_company,operational_status) VALUES (9101,'synthetic','00000000000011','synthetic','active'),(9102,'synthetic','00000000000012','synthetic','active')"))
        db.execute(text("INSERT INTO clients (id,company_id,ownership_company_id,is_active) VALUES (9101,9101,9101,true),(9102,9102,9102,true)"))
        db.execute(text("INSERT INTO contacts (client_id,company_id,phone,name,unread_count) VALUES (9101,9101,'5500000000011','synthetic-one',1),(9101,9102,'5500000000011','synthetic-two',0),(9102,9102,'5500000000012','synthetic-other',0)"))
        db.commit()
        user = Client(id=9101, email="synthetic@invalid")
        options = dict(user=user, db=db, q_client_id=None, q_company_id=None, limit=50, offset=0, search=None, unread_only=False, show_archived=False, archived_only=False, funnel_stages=None, active_flows=None, history_only=False)
        result = get_contacts(**options)
        assert len(result["contacts"]) == 2
        assert "follow_up" in result["unavailable_flow_types"]
        assert result["archive_available"] is False
        assert all("flow_progress" in contact for contact in result["contacts"])
        scoped = get_contacts(**{**options, "q_company_id": 9101})
        assert len(scoped["contacts"]) == 1
        unread = get_contacts(**{**options, "unread_only": True})
        assert len(unread["contacts"]) == 1
        searched = get_contacts(**{**options, "search": "synthetic-two"})
        assert len(searched["contacts"]) == 1
        paginated = get_contacts(**{**options, "limit": 1})
        assert len(paginated["contacts"]) == 1
        assert paginated["total"] == 2
        with pytest.raises(HTTPException) as archive_exc:
            get_contacts(**{**options, "archived_only": True})
        assert archive_exc.value.status_code == 503
        with pytest.raises(HTTPException) as exc:
            get_contacts(**{**options, "active_flows": "follow_up"})
        assert exc.value.status_code == 503
    finally:
        db.close()
        engine.dispose()
