from fastapi import HTTPException

from backend.models import Client
from backend.routes.webhook import get_contacts


class _Result:
    def __init__(self, scalar_value=None, rows=None):
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar(self):
        return self._scalar_value

    def fetchall(self):
        return self._rows


class _SchemaWithoutOptionalFlows:
    def __init__(self):
        self.contact_query = ""

    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            relation = (params or {})["relation"]
            return _Result(scalar_value=not relation.endswith("_executions"))
        if "information_schema.columns" in sql:
            return _Result(scalar_value=False)
        if "FROM contacts c" in sql:
            self.contact_query = sql
            return _Result(rows=[])
        raise AssertionError(f"Unexpected query: {sql}")


def _contacts_kwargs(**overrides):
    values = {
        "q_client_id": None,
        "q_company_id": None,
        "limit": 50,
        "offset": 0,
        "search": None,
        "unread_only": False,
        "show_archived": False,
        "archived_only": False,
        "funnel_stages": None,
        "active_flows": None,
        "history_only": False,
    }
    values.update(overrides)
    return values


def test_contacts_omits_optional_flow_queries_when_tables_are_absent():
    db = _SchemaWithoutOptionalFlows()
    result = get_contacts(user=Client(id=1, email="admin@example.test"), db=db, **_contacts_kwargs())

    assert result["contacts"] == []
    assert "NULL::json as follow_up_progress" in db.contact_query
    assert "FROM follow_up_executions" not in db.contact_query
    assert "c.archived" not in db.contact_query


def test_contacts_rejects_filter_for_an_unavailable_flow():
    db = _SchemaWithoutOptionalFlows()

    try:
        get_contacts(
            user=Client(id=1, email="admin@example.test"),
            db=db,
            **_contacts_kwargs(active_flows="follow_up"),
        )
    except HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("Expected unavailable flow filter to return HTTP 503")
