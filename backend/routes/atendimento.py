from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from backend.db import get_db
from backend.models import Contact
from backend.services.chat_access import require_contact_access
from backend.auth import get_current_user
from backend.ws_manager import manager  # <-- gerenciador de conexões WS, deve ter 'async def broadcast'

router = APIRouter(prefix="/atendimento", tags=["Atendimento"])

@router.post("/take_over/{phone}")
async def take_over(
    phone: str,
    client_id: int = Query(..., description="ID do client, recebido via query param"),
    company_id: int = Query(..., description="ID da empresa, recebido via query param"),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Rota para puxar o atendimento para modo humano (human_mode=True).
    Exemplo de uso:
      POST /api/atendimento/take_over/550000000015?client_id=6&company_id=1
    """
    contact = require_contact_access(db, user, company_id, phone, client_id)

    # 2) Atualiza 'human_mode' = True no banco
    contact.human_mode = True
    db.commit()
    db.refresh(contact)

    # 3) Cria resposta HTTP
    response = {
        "message": f"Contato phone={phone} puxado para modo humano.",
        "human_mode": True
    }

    # 4) Monta dados do broadcast e envia a todos os WS
    broadcast_data = {
        "type": "contact_mode_changed",
        "phone": phone,
        "company_id": company_id,
        "client_id": client_id,
        "human_mode": True
    }

    # OBS: Necessário que seu manager possua 'async def broadcast(...)'
    await manager.broadcast(json.dumps(broadcast_data))

    return response


@router.post("/release_to_bot/{phone}")
async def release_to_bot(
    phone: str,
    client_id: int = Query(..., description="ID do client, recebido via query param"),
    company_id: int = Query(..., description="ID da empresa, recebido via query param"),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Rota para devolver o atendimento para a IA (human_mode=False).
    Exemplo de uso:
      POST /api/atendimento/release_to_bot/550000000015?client_id=6&company_id=1
    """
    contact = require_contact_access(db, user, company_id, phone, client_id)

    # 2) Atualiza 'human_mode' = False no banco
    contact.human_mode = False
    contact.assigned_user_id = None
    db.commit()
    db.refresh(contact)

    # 3) Cria resposta HTTP
    response = {
        "message": f"Contato phone={phone} devolvido para a IA.",
        "human_mode": False
    }

    # 4) Monta dados do broadcast e envia a todos os WS
    broadcast_data = {
        "type": "contact_mode_changed",
        "phone": phone,
        "company_id": company_id,
        "client_id": client_id,
        "human_mode": False
    }

    await manager.broadcast(json.dumps(broadcast_data))

    return response
