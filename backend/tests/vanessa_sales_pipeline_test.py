import asyncio
import json
from uuid import uuid4

from backend.db import SessionLocal
from backend.models import Client, Company, Contact, User
from backend.services.vanessa_sales_pipeline import (
    STAGES,
    choose_round_robin_assignee,
    ensure_sales_lead,
    move_sales_lead,
    provision_sales_pipeline,
)
from backend.agents_sdk.tools.crm_pipeline_tools import create_crm_pipeline_tools


def _seed_company(db):
    suffix = uuid4().int % 10**9
    company = Company(name=f"MVP {suffix}", cnpj=f"{suffix:014d}")
    db.add(company)
    db.flush()
    client = Client(email=f"mvp-{suffix}@test.invalid", password="x", company_id=company.id, ownership_company_id=company.id)
    db.add(client)
    db.flush()
    first = User(client_id=client.id, company_id=company.id, email=f"seller-a-{suffix}@test.invalid", password="x", name="A", role="staff")
    second = User(client_id=client.id, company_id=company.id, email=f"seller-b-{suffix}@test.invalid", password="x", name="B", role="staff")
    db.add_all([first, second])
    db.flush()
    contact = Contact(client_id=client.id, company_id=company.id, phone=f"55{suffix:011d}"[-13:], name="Lead")
    db.add(contact)
    db.commit()
    return company, client, first, second, contact


def test_retail_pipeline_is_idempotent_and_links_one_contact_to_one_lead():
    db = SessionLocal()
    try:
        company, _client, first, second, contact = _seed_company(db)
        first_pipeline = provision_sales_pipeline(db, company_id=company.id)
        db.commit()
        second_pipeline = provision_sales_pipeline(db, company_id=company.id)
        assert first_pipeline.pipeline.id == second_pipeline.pipeline.id
        assert list(second_pipeline.stage_ids) == [key for key, *_ in STAGES]

        lead = move_sales_lead(db, contact=contact, stage_key="new_lead", notes="entrada automática")
        assert lead.contact_id == contact.id
        assert lead.current_stage_id == second_pipeline.stage_ids["new_lead"]
        assert ensure_sales_lead(db, contact=contact).id == lead.id

        move_sales_lead(db, contact=contact, stage_key="qualification", notes="qualificação confirmada")
        move_sales_lead(db, contact=contact, stage_key="catalog_sent", notes="envio confirmado")
        contact.assigned_user_id = first.id
        contact.human_mode = True
        db.commit()
        move_sales_lead(db, contact=contact, stage_key="prints_received", notes="prints confirmados")
        move_sales_lead(db, contact=contact, stage_key="distributed", notes="handoff", require_assigned=True)
        move_sales_lead(db, contact=contact, stage_key="assembling_order", notes="ação humana", actor_user_id=first.id, require_assigned=True)
        move_sales_lead(db, contact=contact, stage_key="awaiting_payment", notes="ação humana", actor_user_id=first.id, require_assigned=True)
        finished = move_sales_lead(db, contact=contact, stage_key="sale_completed", notes="ação humana", actor_user_id=first.id, require_assigned=True)
        assert finished.current_stage_id == second_pipeline.stage_ids["sale_completed"]

        assert choose_round_robin_assignee(db, company_id=company.id, user_ids=[first.id, second.id]) == first.id
        assert choose_round_robin_assignee(db, company_id=company.id, user_ids=[first.id, second.id]) == second.id
    finally:
        db.close()


def test_ana_retail_event_tool_moves_a_real_company_contact():
    db = SessionLocal()
    try:
        company, _client, _first, _second, contact = _seed_company(db)
        provision_sales_pipeline(db, company_id=company.id)
        db.commit()

        tool = next(
            item for item in create_crm_pipeline_tools(company_id=company.id)
            if getattr(item, "name", "") == "record_retail_sales_event"
        )
        result = asyncio.run(tool.on_invoke_tool(None, json.dumps({
            "event": "catalog_sent",
            "evidence": "catálogo enviado ao cliente nesta conversa",
            "lead_phone": contact.phone,
        })))
        assert result["success"] is True
        assert result["stage_key"] == "catalog_sent"
        lead = ensure_sales_lead(db, contact=contact)
        pipeline = provision_sales_pipeline(db, company_id=company.id)
        assert lead.current_stage_id == pipeline.stage_ids["catalog_sent"]
    finally:
        db.close()
