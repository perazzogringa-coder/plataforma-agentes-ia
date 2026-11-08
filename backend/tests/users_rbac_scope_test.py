"""Focused RBAC regression tests for ``backend.routes.users``.

These tests intentionally use fake sessions and model instances: no production
connection, migration, or persistent application database is involved.  They
exercise the route functions and the server-side scope resolver directly.
"""

import asyncio
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


# backend.db requires an explicit URL at import time.  This is an isolated,
# throw-away SQLite file; the tests below do not create application tables.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/vanessa-rbac-isolated.db")

from backend.models import Client, ClientCompany, Company, User  # noqa: E402
from backend.routes import users  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Query:
    def __init__(self, result=None, results=None):
        self.result = result
        self.results = list(results or [])
        self.criteria = []

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.results


class FakeDB:
    def __init__(self, *, links=None, owner=None, company=None, user=None, users_list=None):
        self.links = links
        self.owner = owner
        self.company = company
        self.user = user
        self.users_list = users_list or []
        self.queries = []
        self.commits = self.rollbacks = self.refreshes = self.deleted = 0

    def query(self, model):
        if model is ClientCompany:
            query = Query(result=self.links)
        elif model is Client:
            query = Query(result=self.owner)
        elif model is User:
            query = Query(result=self.user, results=self.users_list)
        elif model is Company:
            query = Query(result=self.company)
        else:
            query = Query()
        self.queries.append((model, query))
        return query

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _value):
        self.refreshes += 1

    def delete(self, _value):
        self.deleted += 1

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = 700
        self.added = value


def master(client_id=100, company_id=10):
    return Client(
        id=client_id,
        email=f"master-{client_id}@example.test",
        company_id=company_id,
        ownership_company_id=company_id,
        is_active=True,
    )


def internal_user(user_id=501, *, role="staff", company_id=20, client_id=200):
    return SimpleNamespace(
        id=user_id,
        role=role,
        company_id=company_id,
        client_id=client_id,
        email=f"user-{user_id}@example.test",
        is_active=True,
        auth_token_version=4,
        password="old",
    )


def owner(client_id=200, company_id=20):
    return Client(
        id=client_id,
        email=f"owner-{client_id}@example.test",
        company_id=company_id,
        ownership_company_id=company_id,
        is_active=True,
    )


def scope(company_id=20, owner_client_id=200, is_master=False):
    return users.UserAdministrationScope(company_id, owner_client_id, is_master)


def query_for(db, model):
    return [query for seen_model, query in db.queries if seen_model is model][-1]


def assert_tenant_filter(query, company_id=20, client_id=200):
    values_by_column = {
        str(criterion.left): getattr(criterion.right, "value", None)
        for criterion in query.criteria
        if hasattr(criterion, "left") and hasattr(criterion, "right")
    }
    assert values_by_column["users.client_id"] == client_id
    assert values_by_column["users.company_id"] == company_id


def test_master_scope_requires_explicit_company_link_and_uses_company_owner():
    db = FakeDB(links=SimpleNamespace(), owner=owner(200, 20))
    resolved = run(users.resolve_user_administration_scope(db, master(), 20))
    assert resolved == scope(20, 200, True)

    denied = FakeDB(links=None, owner=owner(200, 20))
    with pytest.raises(HTTPException, match="Sem permissão") as exc:
        run(users.resolve_user_administration_scope(denied, master(), 20))
    assert exc.value.status_code == 403


def test_same_client_id_does_not_merge_company_scopes():
    # Company 20 and company 21 may share other IDs; the effective company and
    # its active owner are still both required by the scope resolver.
    admin = internal_user(501, role="admin", company_id=20, client_id=200)
    db = FakeDB(owner=owner(200, 20))
    assert run(users.resolve_user_administration_scope(db, admin)) == scope(20, 200, False)
    with pytest.raises(HTTPException) as exc:
        run(users.resolve_user_administration_scope(db, admin, 21))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["manager", "staff"])
def test_manager_and_staff_cannot_get_administration_scope(role):
    db = FakeDB(owner=owner())
    with pytest.raises(HTTPException) as exc:
        run(users.resolve_user_administration_scope(db, internal_user(role=role)))
    assert exc.value.status_code == 403


def test_list_and_get_are_bounded_by_owner_and_company(monkeypatch):
    target = internal_user()
    db = FakeDB(user=target, users_list=[target])

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    assert run(users.list_users(db=db, current_user=internal_user(role="admin"))) == [target]
    assert_tenant_filter(query_for(db, User))

    assert run(users.get_user(501, db=db, current_user=internal_user(role="admin"))) is target
    assert_tenant_filter(query_for(db, User))


def test_get_and_delete_reject_cross_company_target(monkeypatch):
    db = FakeDB(user=None)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    principal = internal_user(role="admin")
    for operation in (users.get_user, users.delete_user):
        with pytest.raises(HTTPException) as exc:
            run(operation(999, db=db, current_user=principal))
        assert exc.value.status_code == 404
    assert db.deleted == 0


def test_update_blocks_admin_role_escalation_and_invalidates_changed_user(monkeypatch):
    target = internal_user(502, role="staff")
    db = FakeDB(user=target)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    principal = internal_user(501, role="admin")
    with pytest.raises(HTTPException) as exc:
        run(users.update_user(502, users.UserUpdate(role="admin"), db=db, current_user=principal))
    assert exc.value.status_code == 403
    assert target.role == "staff"

    result = run(users.update_user(502, users.UserUpdate(name="Changed"), db=db, current_user=principal))
    assert result is target
    assert target.name == "Changed"
    assert target.auth_token_version == 5
    assert db.commits == 1
    assert_tenant_filter(query_for(db, User))


def test_admin_cannot_change_or_delete_own_account_or_another_admin(monkeypatch):
    admin = internal_user(501, role="admin")
    db = FakeDB(user=admin)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    with pytest.raises(HTTPException) as exc:
        run(users.update_user(501, users.UserUpdate(name="no"), db=db, current_user=admin))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        run(users.delete_user(501, db=db, current_user=admin))
    assert exc.value.status_code == 403


def test_create_forbids_company_admin_from_granting_admin(monkeypatch):
    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    payload = users.UserCreate(
        email="new@example.org", name="New", role="admin", company_id=20,
        password="password", confirm_password="password",
    )
    with pytest.raises(HTTPException) as exc:
        run(users._create_user_with_identity_reservation(
            user_data=payload, db=FakeDB(), current_user=internal_user(role="admin"),
        ))
    assert exc.value.status_code == 403


def test_master_can_create_and_grant_admin_only_in_authorized_company(monkeypatch):
    db = FakeDB(owner=owner(), company=SimpleNamespace(operational_status="active"))

    async def resolved(*_args, **_kwargs):
        return scope(is_master=True)

    async def email_available(*_args, **_kwargs):
        return "new@example.org"

    async def valid_team(*_args, **_kwargs):
        return None

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    monkeypatch.setattr(users, "validate_email_available", email_available)
    monkeypatch.setattr(users, "validate_team_access", valid_team)
    monkeypatch.setattr(users, "lock_entities_for_mutation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(users, "hash_password", lambda value: f"hash:{value}")
    payload = users.UserCreate(
        email="new@example.org", name="New", role="admin", company_id=20,
        password="password", confirm_password="password",
    )
    created = run(users._create_user_with_identity_reservation(
        user_data=payload, db=db, current_user=master(),
    ))
    assert created.role == "admin"
    assert created.company_id == 20 and created.client_id == 200
    assert db.commits == 1


def test_master_can_change_role_and_invalidates_target_token(monkeypatch):
    target = internal_user(502, role="staff")
    db = FakeDB(user=target)

    async def resolved(*_args, **_kwargs):
        return scope(is_master=True)

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    result = run(users.update_user(
        502, users.UserUpdate(role="admin"), db=db, current_user=master(),
    ))
    assert result is target
    assert target.role == "admin"
    assert target.auth_token_version == 5


def test_change_password_is_scoped_and_invalidates_only_target(monkeypatch):
    target = internal_user(502, role="staff")
    db = FakeDB(user=target, owner=owner())

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    monkeypatch.setattr(users, "_account_identity_locks", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(users, "_revalidate_internal_user_mutation", lambda *_args, **_kwargs: (owner(), target, object()))
    monkeypatch.setattr(users, "hash_password", lambda value: f"hash:{value}")
    result = run(users._change_user_password_with_identity_reservation(
        user_id=502, password_data={"new_password": "new", "confirm_password": "new"},
        db=db, current_user=master(), reservation=object(),
    ))
    assert result is target
    assert target.password == "hash:new"
    assert target.auth_token_version == 5
    assert db.commits == 1
    assert_tenant_filter(query_for(db, User))


def test_change_password_admin_cannot_reset_self_or_another_admin(monkeypatch):
    admin = internal_user(501, role="admin")
    db = FakeDB(user=admin, owner=owner())

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(users, "resolve_user_administration_scope", resolved)
    with pytest.raises(HTTPException) as exc:
        run(users._change_user_password_with_identity_reservation(
            user_id=501, password_data={"new_password": "x", "confirm_password": "x"},
            db=db, current_user=admin, reservation=object(),
        ))
    assert exc.value.status_code == 403
