"""Regression coverage for chat history tenant ownership."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/vanessa-chat-history-scope.db")

from backend.auth import resolve_company_owner_client_id  # noqa: E402
from backend.models import Client, Contact, Message  # noqa: E402
from backend.routes import chat_optimized, webhook  # noqa: E402


class Query:
    def __init__(self, *, first=None, rows=None):
        self.first_result = first
        self.rows = list(rows or [])
        self.criteria = []

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def first(self):
        return self.first_result

    def count(self):
        return len(self.rows)

    def order_by(self, *_args):
        return self

    def limit(self, limit):
        self.rows = self.rows[:limit]
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, owner):
        self.owner = owner
        self.queries = []

    def query(self, model):
        query = Query(first=self.owner if model is Client else None)
        self.queries.append((model, query))
        return query


def criterion_values(query):
    return {
        str(criterion.left): getattr(criterion.right, "value", None)
        for criterion in query.criteria
        if hasattr(criterion, "left") and hasattr(criterion, "right")
    }


def owner(client_id, company_id):
    return Client(
        id=client_id,
        email=f"owner-{client_id}@example.test",
        company_id=company_id,
        ownership_company_id=company_id,
        is_active=True,
    )


def test_owner_resolution_uses_immutable_workspace_ownership():
    db = FakeDB(owner(202, 2))

    assert resolve_company_owner_client_id(db, 2) == 202
    values = criterion_values(db.queries[0][1])
    assert values["clients.company_id"] == 2
    assert values["clients.ownership_company_id"] == 2


def test_owner_resolution_fails_closed_without_active_owner():
    with pytest.raises(HTTPException) as exc:
        resolve_company_owner_client_id(FakeDB(None), 2)

    assert getattr(exc.value, "status_code", None) == 403


def test_authorized_master_reads_selected_workspace_owner_messages(monkeypatch):
    db = FakeDB(owner(202, 2))
    master = SimpleNamespace(id=101, company_id=1, email="manager@example.test")

    async def authorized(*_args, **_kwargs):
        return True

    monkeypatch.setattr(chat_optimized, "verify_company_access", authorized)
    result = asyncio.run(
        chat_optimized.get_paged_messages(
            contact_phone="5511999999999",
            company_id=2,
            user=master,
            db=db,
        )
    )

    assert result["messages"] == []
    message_query = next(query for model, query in db.queries if model is Message)
    values = criterion_values(message_query)
    assert values["messages.client_id"] == 202
    assert values["messages.company_id"] == 2
    assert values["messages.contact_phone"] == "5511999999999"


def test_same_phone_in_another_company_is_not_included(monkeypatch):
    db = FakeDB(owner(202, 2))
    master = SimpleNamespace(id=101, company_id=1, email="manager@example.test")

    async def authorized(*_args, **_kwargs):
        return True

    monkeypatch.setattr(chat_optimized, "verify_company_access", authorized)
    asyncio.run(
        chat_optimized.get_paged_messages(
            contact_phone="5511999999999",
            company_id=2,
            user=master,
            db=db,
        )
    )

    message_query = next(query for model, query in db.queries if model is Message)
    values = criterion_values(message_query)
    assert values["messages.company_id"] == 2
    assert values["messages.client_id"] == 202


def test_legacy_history_keeps_common_account_on_its_workspace_owner(monkeypatch):
    db = FakeDB(owner(202, 2))
    workspace_master = SimpleNamespace(id=202, company_id=2, email="vanessa@example.test")
    authorized_companies = []

    def authorize(user, company_id, session):
        authorized_companies.append((user.id, company_id, session))

    monkeypatch.setattr(webhook, "ensure_user_can_access_company", authorize)
    result = webhook.get_message_history(
        contact_phone="5511999999999",
        user=workspace_master,
        db=db,
    )

    assert result == {"messages": []}
    assert authorized_companies == [(202, 2, db)]
    message_query = next(query for model, query in db.queries if model is Message)
    values = criterion_values(message_query)
    assert values["messages.client_id"] == 202
    assert values["messages.company_id"] == 2


def test_unauthorized_master_cannot_read_selected_workspace(monkeypatch):
    db = FakeDB(owner(202, 2))
    master = SimpleNamespace(id=303, company_id=3, email="outsider@example.test")

    async def denied(*_args, **_kwargs):
        return False

    monkeypatch.setattr(chat_optimized, "verify_company_access", denied)
    result = asyncio.run(
        chat_optimized.get_paged_messages(
            contact_phone="5511999999999",
            company_id=2,
            user=master,
            db=db,
        )
    )

    assert result == {"error": "Acesso negado à empresa solicitada", "messages": []}
    assert not db.queries
