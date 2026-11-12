from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend.services.chat_access import is_chat_administrator, require_contact_access

class Query:
    def __init__(self, contact): self.contact = contact
    def filter(self, *_): return self
    def first(self): return self.contact
class DB:
    def __init__(self, contact): self.contact = contact
    def query(self, _): return Query(self.contact)

def staff(id, role="staff"):
    from backend.models import User
    return User(id=id, client_id=1, company_id=10, email=f"u{id}@test", name="Kethelyn", password="x", role=role)

def test_staff_can_only_open_its_assigned_contact():
    contact = SimpleNamespace(assigned_user_id=7)
    assert require_contact_access(DB(contact), staff(7), 10, "55", 1) is contact
    with pytest.raises(HTTPException) as exc:
        require_contact_access(DB(contact), staff(8), 10, "55", 1)
    assert exc.value.status_code == 403

def test_admin_keeps_company_chat_access():
    assert is_chat_administrator(staff(8, "admin"))
