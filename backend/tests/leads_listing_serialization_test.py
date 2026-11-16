from datetime import datetime, timezone
from types import SimpleNamespace

from backend.services.lead_custom_fields_service import LeadCustomFieldsService
from backend.services.leads_with_custom_fields_service import LeadsWithCustomFieldsService


class _FakeQuery:
    def __init__(self, records):
        self._records = list(records)

    def filter(self, *criteria):
        for criterion in criteria:
            clauses = getattr(criterion, "clauses", (criterion,))
            for clause in clauses:
                column = getattr(getattr(clause, "left", None), "key", None)
                value = getattr(getattr(clause, "right", None), "value", None)
                if column is not None:
                    self._records = [
                        record
                        for record in self._records
                        if str(getattr(record, column)) == str(value)
                    ]
        return self

    def all(self):
        return list(self._records)


class _FakeDb:
    def __init__(self, records):
        self._records = records

    def query(self, _model):
        return _FakeQuery(self._records)


def _lead(*, lead_id, client_id, company_id, pipeline_id, stage_id):
    return SimpleNamespace(
        id=lead_id,
        client_id=client_id,
        company_id=company_id,
        name="Lead de teste",
        phone="5500000000000",
        created_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
        data_entrada=None,
        source_id="test",
        thumbnail_url="https://example.invalid/avatar.png",
        sender_lid=None,
        follow_up_sequence_id=None,
        current_stage_id=stage_id,
        pipeline_id=pipeline_id,
        pipeline_entered_at=None,
        last_stage_move_at=None,
    )


def test_listing_serializes_integer_client_id_and_applies_all_tenant_filters(monkeypatch):
    monkeypatch.setattr(LeadCustomFieldsService, "get_lead_custom_values", lambda *_args: [])

    matching = _lead(lead_id=1, client_id=2, company_id=2, pipeline_id=5, stage_id=26)
    records = [
        matching,
        _lead(lead_id=2, client_id=3, company_id=2, pipeline_id=5, stage_id=26),
        _lead(lead_id=3, client_id=2, company_id=3, pipeline_id=5, stage_id=26),
        _lead(lead_id=4, client_id=2, company_id=2, pipeline_id=4, stage_id=26),
        _lead(lead_id=5, client_id=2, company_id=2, pipeline_id=5, stage_id=25),
    ]

    result = LeadsWithCustomFieldsService.list_leads_with_custom_fields(
        client_id=2,
        company_id=2,
        pipeline_id=5,
        stage_id=26,
        db=_FakeDb(records),
    )

    assert [lead.id for lead in result] == [matching.id]
    assert result[0].client_id == 2
    assert result[0].company_id == 2
    assert result[0].pipeline_id == 5
    assert result[0].current_stage_id == 26


def test_listing_returns_legitimate_empty_list_without_serialization_error(monkeypatch):
    monkeypatch.setattr(LeadCustomFieldsService, "get_lead_custom_values", lambda *_args: [])

    result = LeadsWithCustomFieldsService.list_leads_with_custom_fields(
        client_id=2,
        company_id=2,
        pipeline_id=5,
        stage_id=26,
        db=_FakeDb([]),
    )

    assert result == []
