from types import SimpleNamespace
from backend.ws_manager import ConnectionManager, PRIVATE_USER_TOPIC_PREFIX, WSConnection

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

def test_staff_private_assignment_topic_is_only_its_own_socket():
    staff_user = SimpleNamespace(id=7, client_id=1, is_active=True, auth_token_version=0, role="staff")
    manager = ConnectionManager()
    assert manager._connection_principal_is_active(DB(staff_user, None), socket(f"{PRIVATE_USER_TOPIC_PREFIX}7"))
    assert not manager._connection_principal_is_active(DB(staff_user, None), socket(f"{PRIVATE_USER_TOPIC_PREFIX}8"))

def test_assignment_notification_uses_private_user_topic(monkeypatch):
    manager = ConnectionManager()
    seen = {}

    async def record(company_id, phone, message, **kwargs):
        seen.update(company_id=company_id, phone=phone, message=message)
        return "delivered"

    monkeypatch.setattr(manager, "broadcast_to_phone", record)
    import asyncio
    result = asyncio.run(manager.notify_chat_assignment(
        company_id=10, user_id=7, message={"phone": "5511"}
    ))
    assert result == "delivered"
    assert seen["phone"] == f"{PRIVATE_USER_TOPIC_PREFIX}7"
    assert seen["message"]["type"] == "contact_assignment_changed"
