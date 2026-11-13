from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.models import Client, Contact, User
from backend.services.chat_assignment import (
    assign_chat_contact,
    require_chat_assignment_administrator,
)


class Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *_):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.value


class DB:
    def __init__(self, contact, assignee):
        self.contact = contact
        self.assignee = assignee

    def query(self, model):
        return Query(self.contact if model is Contact else self.assignee)


def staff(user_id=4, *, company_id=2, client_id=2, active=True):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
        client_id=client_id,
        is_active=active,
        role="staff",
    )


def test_assignment_pauses_contact_and_is_idempotent():
    contact = SimpleNamespace(
        company_id=2,
        client_id=2,
        phone="5511",
        assigned_user_id=None,
        human_mode=False,
    )
    db = DB(contact, staff())

    first = assign_chat_contact(
        db, company_id=2, client_id=2, phone="5511", assignee_user_id=4
    )
    assert first.changed
    assert contact.assigned_user_id == 4
    assert contact.human_mode is True

    second = assign_chat_contact(
        db, company_id=2, client_id=2, phone="5511", assignee_user_id=4
    )
    assert not second.changed


def test_assignment_rejects_missing_cross_tenant_or_inactive_assignee():
    contact = SimpleNamespace(
        company_id=2, client_id=2, phone="5511", assigned_user_id=None, human_mode=False
    )
    with pytest.raises(HTTPException) as exc:
        assign_chat_contact(
            DB(contact, None), company_id=2, client_id=2, phone="5511", assignee_user_id=99
        )
    assert exc.value.status_code == 404


def test_only_company_master_or_admin_can_assign():
    master = Client(id=2, company_id=2, ownership_company_id=2)
    require_chat_assignment_administrator(master, company_id=2, client_id=2)

    with pytest.raises(HTTPException) as exc:
        require_chat_assignment_administrator(staff(), company_id=2, client_id=2)
    assert exc.value.status_code == 403

    admin = User(id=9, client_id=2, company_id=2, email="admin@test", name="Admin", password="x", role="admin")
    require_chat_assignment_administrator(admin, company_id=2, client_id=2)
