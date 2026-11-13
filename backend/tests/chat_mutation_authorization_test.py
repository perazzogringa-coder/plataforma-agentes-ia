"""Endpoint-level fail-closed checks for chat mutations.

Each route is invoked with the real Pydantic body and a denying contact guard;
the provider/database side-effect boundary must never be reached.
"""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend.routes import webhook
from backend.routes import atendimento
from backend.services.chat_assignment import ChatAssignment

def denied(*_args, **_kwargs):
    raise HTTPException(status_code=403, detail="Acesso negado a esta conversa")

@pytest.mark.parametrize("route,body", [
    (webhook.send_message_reaction, webhook.WhatsAppReactionBody(phone="5511", messageId="m", reaction="👍")),
    (webhook.send_image, webhook.WhatsAppSendImageBody(phone="5511", image="data:image/png;base64,AA==")),
    (webhook.send_audio, webhook.WhatsAppSendAudioBody(phone="5511", audio="data:audio/ogg;base64,AA==")),
    (webhook.send_video, webhook.WhatsAppSendVideoBody(phone="5511", video="data:video/mp4;base64,AA==")),
])
def test_unassigned_staff_is_denied_before_mutating_provider(monkeypatch, route, body):
    monkeypatch.setattr(webhook, "_require_whatsapp_scope", lambda *_: None)
    monkeypatch.setattr(webhook, "require_contact_access", denied)
    with pytest.raises(HTTPException) as exc:
        route(body=body, client_id=1, company_id=10, db=SimpleNamespace(), user=SimpleNamespace())
    assert exc.value.status_code == 403

def test_unassigned_staff_cannot_mark_contact_read(monkeypatch):
    monkeypatch.setattr(webhook, "_require_whatsapp_scope", lambda *_: None)
    monkeypatch.setattr(webhook, "require_contact_access", denied)
    with pytest.raises(HTTPException) as exc:
        webhook.mark_contact_as_read("5511", 1, 10, SimpleNamespace(), SimpleNamespace())
    assert exc.value.status_code == 403

@pytest.mark.parametrize("handoff", [atendimento.take_over, atendimento.release_to_bot])
def test_unassigned_staff_cannot_change_human_mode(monkeypatch, handoff):
    monkeypatch.setattr(atendimento, "require_contact_access", denied)
    with pytest.raises(HTTPException) as exc:
        __import__('asyncio').run(handoff("5511", 1, 10, SimpleNamespace(), SimpleNamespace()))
    assert exc.value.status_code == 403


def test_reassignment_revokes_only_the_previous_staff_socket(monkeypatch):
    calls = []
    contact = SimpleNamespace(phone="5511", human_mode=True)
    assignee = SimpleNamespace(id=4)

    monkeypatch.setattr(atendimento, "require_chat_assignment_administrator", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        atendimento,
        "assign_chat_contact",
        lambda *_args, **_kwargs: ChatAssignment(contact, assignee, True, 7),
    )

    async def revoked(company_ids, *, user_ids=()):
        calls.append((company_ids, list(user_ids)))

    async def notified(**_kwargs):
        return "delivered"

    monkeypatch.setattr(atendimento.manager, "publish_access_revocation", revoked)
    monkeypatch.setattr(atendimento.manager, "notify_chat_assignment", notified)
    db = SimpleNamespace(commit=lambda: None, refresh=lambda _contact: None)

    result = __import__('asyncio').run(atendimento.assign_attendant(
        "5511", atendimento.AssignAttendantRequest(assignee_user_id=4), 2, 2, db, SimpleNamespace()
    ))

    assert result["assigned_user_id"] == 4
    assert calls == [([], [7])]
