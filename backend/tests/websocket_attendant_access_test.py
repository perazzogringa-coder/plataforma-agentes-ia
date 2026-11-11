from types import SimpleNamespace
from backend.ws_manager import ConnectionManager, WSConnection

class Query:
    def __init__(self, value): self.value = value
    def filter(self, *_): return self
    def first(self): return self.value

class DB:
    def __init__(self, user, contact): self.user, self.contact = user, contact
    def query(self, model):
        from backend.models import Client, Contact
        if model is Client: return Query(SimpleNamespace(id=1, is_active=True, auth_token_version=0))
        if model is Contact: return Query(self.contact)
        return Query(self.user)

def socket(phone):
    return WSConnection(websocket=None, client_id="1", company_id=10, phone=phone,
        connected_at=None, user_id="7", user_type="user", auth_token_version=0, access_epoch=1)

def test_staff_delivery_is_denied_for_global_and_unassigned_topics():
    staff = SimpleNamespace(id=7, client_id=1, is_active=True, auth_token_version=0, role="staff")
    manager = ConnectionManager()
    assert not manager._connection_principal_is_active(DB(staff, None), socket("__global__"))
    assert not manager._connection_principal_is_active(DB(staff, None), socket("5511"))

def test_admin_delivery_remains_authorized_for_workspace_topics():
    admin = SimpleNamespace(id=7, client_id=1, is_active=True, auth_token_version=0, role="admin")
    assert ConnectionManager()._connection_principal_is_active(DB(admin, None), socket("__global__"))
