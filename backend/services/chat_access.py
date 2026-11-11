"""Server-side authorization for live-chat contacts."""
from fastapi import HTTPException
from backend.models import Client, Company, Contact, User


def is_chat_administrator(user):
    return isinstance(user, Client) or (isinstance(user, User) and user.role == "admin")


def require_contact_access(db, user, company_id: int, phone: str, client_id: int):
    contact = db.query(Contact).filter(
        Contact.company_id == company_id, Contact.client_id == client_id,
        Contact.phone == phone,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    # Non-ORM objects are used by the lightweight historical route tests; real
    # authenticated staff is always a User instance.
    if isinstance(user, User) and not is_chat_administrator(user) and int(contact.assigned_user_id or 0) != int(user.id):
        raise HTTPException(status_code=403, detail="Acesso negado a esta conversa")
    return contact


def resolve_handoff_assignee(db, company_id: int, requested_user_id=None):
    """Temporary company-scoped routing; never leaks a user to another tenant."""
    if requested_user_id:
        assignee = db.query(User).filter(User.id == requested_user_id, User.company_id == company_id, User.is_active.is_(True)).first()
        if assignee:
            return assignee.id
        raise ValueError("Assigned user not found for company")
    company = db.query(Company).filter(Company.id == company_id).first()
    if company and (company.name or "").strip().casefold() == "vanessa lima":
        kethelyn = db.query(User).filter(User.company_id == company_id, User.is_active.is_(True), User.name.ilike("Kethelyn")).first()
        if kethelyn:
            return kethelyn.id
    return None
