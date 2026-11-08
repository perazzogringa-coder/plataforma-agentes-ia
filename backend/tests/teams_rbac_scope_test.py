"""RBAC boundary tests for team administration routes (no real database)."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/vanessa-rbac-isolated.db")

from backend.models import Team, User  # noqa: E402
from backend.routes import teams  # noqa: E402
from backend.routes.users import UserAdministrationScope  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Query:
    def __init__(self, result=None, results=None):
        self.result = result
        self.results = list(results or [])
        self.criteria = []
        self.updated = None

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.results

    def update(self, values, **_kwargs):
        self.updated = values
        return 1


class FakeDB:
    def __init__(self, *, team=None, user=None, teams_list=None):
        self.team = team
        self.user = user
        self.teams_list = teams_list or []
        self.queries = []
        self.commits = 0

    def query(self, model):
        query = Query(
            result=self.team if model is Team else self.user,
            results=self.teams_list if model is Team else ([self.user] if self.user is not None else []),
        )
        self.queries.append((model, query))
        return query

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def delete(self, _value):
        pass

    def refresh(self, _value):
        pass


def scope():
    return UserAdministrationScope(company_id=20, owner_client_id=200, is_master=False)


def admin():
    return SimpleNamespace(id=501, role="admin", company_id=20, client_id=200, email="admin@example.org")


def test_manager_and_staff_cannot_administer_teams(monkeypatch):
    async def deny(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Acesso permitido apenas para administradores")

    monkeypatch.setattr(teams, "resolve_user_administration_scope", deny)
    for role in ("manager", "staff"):
        principal = SimpleNamespace(role=role, company_id=20, client_id=200, email=f"{role}@example.org")
        with pytest.raises(HTTPException) as exc:
            run(teams.list_teams(db=FakeDB(), current_user=principal))
        assert exc.value.status_code == 403


def test_team_user_listing_uses_company_and_owner_client(monkeypatch):
    team = SimpleNamespace(id=70, company_id=20)
    member = SimpleNamespace(id=502, name="Member", email="member@example.org", role="staff", team_id=70, is_active=True)
    db = FakeDB(team=team, user=member)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(teams, "resolve_team_administration_scope", resolved)
    result = run(teams.list_team_users(70, db=db, current_user=admin()))
    assert result[0]["id"] == 502
    user_query = [query for model, query in db.queries if model is User][-1]
    rendered = " ".join(str(item) for item in user_query.criteria)
    assert "users.company_id" in rendered and "users.client_id" in rendered


def test_cross_company_assignment_is_not_found_and_does_not_mutate(monkeypatch):
    db = FakeDB(team=SimpleNamespace(id=70, company_id=20), user=None)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(teams, "resolve_team_administration_scope", resolved)
    with pytest.raises(HTTPException) as exc:
        run(teams.assign_user_to_team(70, teams.AssignUserRequest(user_id=999), db=db, current_user=admin()))
    assert exc.value.status_code == 404
    assert db.commits == 0


def test_team_assignment_invalidates_only_changed_member(monkeypatch):
    member = SimpleNamespace(id=502, name="Member", email="member@example.org", team_id=None, auth_token_version=7)
    db = FakeDB(team=SimpleNamespace(id=70, company_id=20, name="Support"), user=member)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(teams, "resolve_team_administration_scope", resolved)
    run(teams.assign_user_to_team(70, teams.AssignUserRequest(user_id=502), db=db, current_user=admin()))
    assert member.team_id == 70
    assert member.auth_token_version == 8
    assert db.commits == 1


def test_team_permission_update_invalidates_scoped_members(monkeypatch):
    team = SimpleNamespace(id=70, company_id=20, name="Support", code="SUPPORT", description=None, permissions=[])
    db = FakeDB(team=team)

    async def resolved(*_args, **_kwargs):
        return scope()

    monkeypatch.setattr(teams, "resolve_team_administration_scope", resolved)
    monkeypatch.setattr(teams, "_apply_team_permissions", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(teams, "_extract_team_permissions", lambda *_args, **_kwargs: {
        "sidebar_permissions": [], "contact_permissions": {"include_outside_crm": False, "pipeline_stage_ids": []},
    })
    monkeypatch.setattr(teams, "_team_to_response", lambda *_args, **_kwargs: {"id": 70})
    run(teams.update_team(70, teams.TeamUpdate(description="Updated"), db=db, current_user=admin()))
    user_query = [query for model, query in db.queries if model is User][-1]
    rendered = " ".join(str(item) for item in user_query.criteria)
    assert "users.team_id" in rendered and "users.company_id" in rendered and "users.client_id" in rendered
    assert user_query.updated is not None
