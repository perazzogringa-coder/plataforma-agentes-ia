from fastapi import HTTPException

from backend.models import Client
from backend.routes import webhook
from backend.routes.webhook import get_contacts, get_contacts_no_history


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


class _CountResult(_Result):
    def __init__(self, total=0):
        super().__init__()
        self.total = total

    def fetchone(self):
        return self


class _ScopedContactsDb:
    """Records contact-list SQL without using a database."""

    def __init__(self):
        self.contact_queries = []

    def execute(self, statement, params=None):
        sql = str(statement)
        if "to_regclass" in sql:
            return _Result(scalar_value=False)
        if "information_schema.columns" in sql:
            return _Result(scalar_value=False)
        if "FROM contacts c" in sql:
            self.contact_queries.append((sql, dict(params or {})))
            if "COUNT(" in sql:
                return _CountResult()
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


def test_master_list_uses_selected_workspace_owner_after_authorization(monkeypatch):
    db = _ScopedContactsDb()
    master = Client(id=101, email="master@example.test")
    authorized_companies = []

    monkeypatch.setattr(
        webhook,
        "ensure_user_can_access_company",
        lambda _user, company_id, _db: authorized_companies.append(company_id),
    )
    monkeypatch.setattr(webhook, "resolve_company_owner_client_id", lambda _db, company_id: 202)

    result = get_contacts(
        user=master,
        db=db,
        **_contacts_kwargs(
            q_client_id=101,
            q_company_id=2,
            limit=20,
            offset=7,
            search="Marcelo",
            unread_only=True,
        ),
    )

    assert result["contacts"] == []
    assert authorized_companies == [2]
    sql, params = db.contact_queries[0]
    assert "c.client_id = :cid AND c.company_id = :company_id" in sql
    assert "c.unread_count > 0" in sql
    assert params["cid"] == 202
    assert params["company_id"] == 2
    assert params["offset"] == 7
    assert params["search"] == "%marcelo%"


def test_master_list_rejects_unlinked_selected_workspace_before_query(monkeypatch):
    db = _ScopedContactsDb()
    master = Client(id=101, email="master@example.test")

    def denied(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")

    monkeypatch.setattr(webhook, "ensure_user_can_access_company", denied)
    monkeypatch.setattr(
        webhook,
        "resolve_company_owner_client_id",
        lambda *_args: (_ for _ in ()).throw(AssertionError("owner must not be resolved")),
    )

    try:
        get_contacts(user=master, db=db, **_contacts_kwargs(q_company_id=99))
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("Expected an unlinked workspace to be rejected")

    assert db.contact_queries == []


def test_master_no_history_rejects_unlinked_selected_workspace_before_query(monkeypatch):
    db = _ScopedContactsDb()
    master = Client(id=101, email="master@example.test")

    def denied(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")

    monkeypatch.setattr(webhook, "ensure_user_can_access_company", denied)

    try:
        get_contacts_no_history(
            user=master,
            db=db,
            q_client_id=101,
            q_company_id=99,
            limit=20,
            offset=0,
            search=None,
        )
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("Expected an unlinked workspace to be rejected")

    assert db.contact_queries == []


def test_master_no_history_uses_selected_workspace_owner_after_authorization(monkeypatch):
    db = _ScopedContactsDb()
    master = Client(id=101, email="master@example.test")
    authorized_companies = []

    monkeypatch.setattr(
        webhook,
        "ensure_user_can_access_company",
        lambda _user, company_id, _db: authorized_companies.append(company_id),
    )
    monkeypatch.setattr(webhook, "resolve_company_owner_client_id", lambda _db, company_id: 202)

    result = get_contacts_no_history(
        user=master,
        db=db,
        q_client_id=101,
        q_company_id=2,
        limit=20,
        offset=7,
        search="Marcelo",
    )

    assert result["contacts"] == []
    assert result["total"] == 0
    assert authorized_companies == [2]
    for sql, params in db.contact_queries:
        assert "c.client_id = :cid AND c.company_id = :company_id" in sql
        assert params["cid"] == 202
        assert params["company_id"] == 2
    assert db.contact_queries[0][1]["offset"] == 7
    assert db.contact_queries[0][1]["search"] == "%marcelo%"


def test_staff_list_keeps_assigned_user_boundary():
    db = _ScopedContactsDb()
    staff = type(
        "Staff",
        (),
        {
            "id": 4,
            "email": "staff@example.test",
            "client_id": 202,
            "company_id": 2,
            "role": "staff",
            "team_id": None,
        },
    )()

    get_contacts(user=staff, db=db, **_contacts_kwargs(q_client_id=101, q_company_id=99))

    sql, params = db.contact_queries[-1]
    assert "c.client_id = :master_id AND c.company_id = :company_id" in sql
    assert "c.assigned_user_id = 4" in sql
    assert params["master_id"] == 202
    assert params["company_id"] == 2
