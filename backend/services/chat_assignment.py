"""Atomic, tenant-scoped live-chat assignment operations."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import Client, Contact, User


@dataclass(frozen=True)
class ChatAssignment:
    contact: Contact
    assignee: User
    changed: bool
    previous_assignee_id: int | None


def require_chat_assignment_administrator(
    actor: Client | User,
    *,
    company_id: int,
    client_id: int,
) -> None:
    """Allow assignment only to the owning master or a company admin."""
    if isinstance(actor, Client):
        allowed = int(actor.id) == int(client_id) and int(actor.company_id) == int(company_id)
    else:
        allowed = (
            actor.role == "admin"
            and int(actor.client_id) == int(client_id)
            and int(actor.company_id) == int(company_id)
        )
    if not allowed:
        raise HTTPException(status_code=403, detail="Sem permissão para atribuir esta conversa")


def assign_chat_contact(
    db: Session,
    *,
    company_id: int,
    client_id: int,
    phone: str,
    assignee_user_id: int,
    pause_bot: bool = True,
) -> ChatAssignment:
    """Lock, assign and pause one chat without crossing company boundaries.

    The caller owns the surrounding transaction. Repeating the same assignment is
    explicitly idempotent so webhook retries cannot create a second handoff.
    """
    contact = (
        db.query(Contact)
        .filter(
            Contact.company_id == int(company_id),
            Contact.client_id == int(client_id),
            Contact.phone == str(phone),
        )
        .with_for_update()
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    assignee = (
        db.query(User)
        .filter(
            User.id == int(assignee_user_id),
            User.company_id == int(company_id),
            User.client_id == int(client_id),
            User.is_active.is_(True),
        )
        .first()
    )
    if assignee is None:
        raise HTTPException(status_code=404, detail="Atendente não encontrado nesta empresa")

    previous_assignee_id = contact.assigned_user_id
    changed = (
        int(contact.assigned_user_id or 0) != int(assignee.id)
        or (bool(pause_bot) and not bool(contact.human_mode))
    )
    if changed:
        contact.assigned_user_id = assignee.id
        contact.human_mode = bool(pause_bot)

    return ChatAssignment(
        contact=contact,
        assignee=assignee,
        changed=changed,
        previous_assignee_id=previous_assignee_id,
    )
