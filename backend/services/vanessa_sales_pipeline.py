"""Small, tenant-scoped commercial pipeline for the Vanessa wholesale pilot.

The service deliberately uses the existing Pipeline/Lead/History model.  It is
inactive until a company administrator explicitly provisions it, and never
changes another company's pipeline or legacy lead rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import Company, Contact, Lead, Pipeline, PipelineStage, User
from backend.services.pipeline_service import PipelineService


PIPELINE_KEY = "vanessa_retail_sales"
STAGES = (
    ("new_lead", "Novo lead", "#2563EB", True, False),
    ("qualification", "Em qualificação", "#7C3AED", False, False),
    ("catalog_sent", "Catálogo enviado", "#0891B2", False, False),
    ("prints_received", "Prints recebidos", "#D97706", False, False),
    ("distributed", "Distribuído à vendedora", "#DB2777", False, False),
    ("assembling_order", "Pedido em montagem", "#EA580C", False, False),
    ("awaiting_payment", "Aguardando pagamento", "#CA8A04", False, False),
    ("sale_completed", "Venda concluída", "#059669", False, True),
)
AUTOMATIC_STAGE_KEYS = frozenset(key for key, *_ in STAGES[:5])
MANUAL_STAGE_KEYS = frozenset(key for key, *_ in STAGES[5:])


@dataclass(frozen=True)
class SalesPipeline:
    pipeline: Pipeline
    stage_ids: dict[str, int]


def provision_sales_pipeline(db: Session, *, company_id: int, actor_user_id: int | None = None) -> SalesPipeline:
    """Idempotently create the eight-stage wholesale pipeline for one company."""
    company = db.query(Company).filter(Company.id == int(company_id)).with_for_update().first()
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    settings = dict(company.settings or {})
    config = dict(settings.get("commercial_pipeline") or {})
    pipeline = None
    if config.get("key") == PIPELINE_KEY and config.get("pipeline_id"):
        pipeline = db.query(Pipeline).filter(
            Pipeline.id == int(config["pipeline_id"]), Pipeline.company_id == int(company_id)
        ).first()
    if pipeline is None:
        pipeline = Pipeline(
            company_id=int(company_id), name="Vendas - Vanessa Lima",
            description="Funil comercial atacado", is_active=True,
            created_by_user_id=actor_user_id,
        )
        db.add(pipeline)
        db.flush()
        for order, (key, name, color, first, converted) in enumerate(STAGES, start=1):
            db.add(PipelineStage(
                pipeline_id=pipeline.id, name=name, color=color, order=order,
                order_index=order, is_first_stage=first,
                is_converted_stage=converted, is_lost_stage=False,
                description=f"Etapa comercial: {key}",
            ))
        db.flush()
    stage_ids = _stage_ids(pipeline)
    if set(stage_ids) != {item[0] for item in STAGES}:
        raise HTTPException(status_code=409, detail="Pipeline comercial possui etapas incompatíveis")
    # Provisioning is an explicit, administrator-only deployment operation. It
    # enables this CRM pipeline, never the separate workforce-3 automation.
    config.update({"key": PIPELINE_KEY, "pipeline_id": pipeline.id, "stage_ids": stage_ids, "enabled": True})
    settings["commercial_pipeline"] = config
    company.settings = settings
    return SalesPipeline(pipeline=pipeline, stage_ids=stage_ids)


def configured_sales_pipeline(db: Session, *, company_id: int) -> SalesPipeline | None:
    company = db.query(Company).filter(Company.id == int(company_id)).first()
    config = dict((company.settings or {}).get("commercial_pipeline") or {}) if company else {}
    if config.get("key") != PIPELINE_KEY or not config.get("pipeline_id") or config.get("enabled") is not True:
        return None
    pipeline = db.query(Pipeline).filter(Pipeline.id == int(config["pipeline_id"]), Pipeline.company_id == int(company_id)).first()
    if not pipeline:
        return None
    stage_ids = _stage_ids(pipeline)
    return SalesPipeline(pipeline=pipeline, stage_ids=stage_ids)


def ensure_sales_lead(db: Session, *, contact: Contact) -> Lead:
    """Resolve one card per contact, without taking ownership of ambiguous legacy leads."""
    existing = db.query(Lead).filter(
        Lead.company_id == contact.company_id, Lead.contact_id == contact.id
    ).with_for_update(of=Lead).first()
    if existing:
        return existing
    candidates = db.query(Lead).filter(
        Lead.company_id == contact.company_id, Lead.contact_id.is_(None), Lead.phone == contact.phone
    ).order_by(Lead.id.asc()).with_for_update(of=Lead).all()
    if len(candidates) == 1:
        candidates[0].contact_id = contact.id
        return candidates[0]
    lead = Lead(
        client_id=contact.client_id, company_id=contact.company_id,
        contact_id=contact.id, name=contact.name, phone=contact.phone,
        source_id=contact.source_id, thumbnail_url=contact.thumbnail_url,
    )
    db.add(lead)
    db.flush()
    return lead


def move_sales_lead(
    db: Session, *, contact: Contact, stage_key: str, notes: str, actor_user_id: int | None = None,
    require_assigned: bool = False,
) -> Lead:
    sales = configured_sales_pipeline(db, company_id=contact.company_id)
    if sales is None:
        raise HTTPException(status_code=409, detail="Pipeline comercial não configurado para esta empresa")
    if stage_key not in sales.stage_ids:
        raise HTTPException(status_code=400, detail="Etapa comercial inválida")
    if require_assigned and not contact.assigned_user_id:
        raise HTTPException(status_code=409, detail="Conversa ainda não foi distribuída")
    lead = ensure_sales_lead(db, contact=contact)
    if lead.pipeline_id not in (None, sales.pipeline.id):
        raise HTTPException(status_code=409, detail="Lead pertence a outro pipeline")
    target_id = sales.stage_ids[stage_key]
    if lead.current_stage_id == target_id:
        return lead
    if lead.pipeline_id is None:
        lead.pipeline_id = sales.pipeline.id
    PipelineService.move_lead_to_stage(
        lead_id=lead.id, new_stage_id=target_id, user_id=actor_user_id,
        notes=notes, db=db,
    )
    return lead


def choose_round_robin_assignee(db: Session, *, company_id: int, user_ids: Iterable[int]) -> int:
    """Choose an active same-company attendant and persist only a cursor."""
    company = db.query(Company).filter(Company.id == int(company_id)).with_for_update().first()
    if not company:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    eligible = db.query(User).filter(
        User.company_id == int(company_id), User.is_active.is_(True), User.id.in_([int(v) for v in user_ids])
    ).order_by(User.id.asc()).all()
    if not eligible:
        raise HTTPException(status_code=409, detail="Nenhuma atendente elegível para rodízio")
    settings = dict(company.settings or {})
    config = dict(settings.get("commercial_pipeline") or {})
    cursor = int(config.get("round_robin_cursor", -1))
    selected = eligible[(cursor + 1) % len(eligible)]
    config["round_robin_cursor"] = eligible.index(selected)
    settings["commercial_pipeline"] = config
    company.settings = settings
    return int(selected.id)


def _stage_ids(pipeline: Pipeline) -> dict[str, int]:
    by_name = {stage.name: stage.id for stage in pipeline.stages}
    return {key: int(by_name[name]) for key, name, *_ in STAGES if name in by_name}
