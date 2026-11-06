"""Regression coverage for WAHA tenant isolation and duplicate delivery."""

import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.worker.process_message_waha import (  # noqa: E402
    _lock_waha_message_processing,
    _touch_contact_last_message,
    _upsert_inbound_contact,
)


class _Result:
    pass


class _RecordingDb:
    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((" ".join(str(query).split()), params))
        return _Result()


def test_same_phone_is_upserted_independently_for_two_companies():
    """T5: a shared phone creates tenant-local contacts, never one shared row."""
    db = _RecordingDb()

    _upsert_inbound_contact(
        db, client_id=7, company_id=101, phone="5500000000001",
        name="Contato A", sender_lid="a@lid",
    )
    _upsert_inbound_contact(
        db, client_id=7, company_id=202, phone="5500000000001",
        name="Contato B", sender_lid="b@lid",
    )

    assert len(db.calls) == 2
    assert [call[1]["company_id"] for call in db.calls] == [101, 202]
    assert all(
        "ON CONFLICT (client_id, company_id, phone)" in call[0]
        for call in db.calls
    )
    assert all("contacts.name" in call[0] for call in db.calls)


def test_message_and_message_any_share_one_tenant_message_lock():
    """T6: concurrent WAHA variants serialize on the same tenant/message key."""
    db = _RecordingDb()

    _lock_waha_message_processing(db, 101, "false_5500000000001@c.us_ABC")
    _lock_waha_message_processing(db, 101, "false_5500000000001@c.us_ABC")

    assert len(db.calls) == 2
    assert all("pg_advisory_xact_lock" in call[0] for call in db.calls)
    assert db.calls[0][1]["dedupe_key"] == db.calls[1][1]["dedupe_key"]
    assert db.calls[0][1]["dedupe_key"].startswith("waha-message:101:")


def test_same_provider_message_id_is_not_shared_between_companies():
    """T11 prerequisite: identical provider IDs remain isolated by company."""
    db = _RecordingDb()

    _lock_waha_message_processing(db, 101, "provider-message")
    _lock_waha_message_processing(db, 202, "provider-message")

    assert db.calls[0][1]["dedupe_key"] != db.calls[1][1]["dedupe_key"]


def test_contact_recency_update_cannot_touch_another_company():
    """T10: contact metadata updates keep the complete tenant key."""
    db = _RecordingDb()

    _touch_contact_last_message(
        db, client_id=7, company_id=202, phone="5500000000001"
    )

    sql, params = db.calls[0]
    assert "company_id = :company_id" in sql
    assert params == {
        "client_id": 7,
        "company_id": 202,
        "contact_phone": "5500000000001",
    }
