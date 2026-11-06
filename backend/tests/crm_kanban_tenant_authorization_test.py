import os
from types import SimpleNamespace

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from backend.routes import crm_kanban  # noqa: E402


def test_board_has_one_pipeline_creation_route():
    """The valid creator must not be shadowed by the historical duplicate route."""
    routes = [
        route for route in crm_kanban.router.routes
        if route.path == "/pipelines" and "POST" in route.methods
    ]

    assert len(routes) == 1
    assert routes[0].endpoint.__name__ == "create_pipeline"


def test_board_authorization_delegates_to_workspace_access_policy(monkeypatch):
    """A master is evaluated by its company links; a staff user by its company."""
    calls = []

    def fake_ensure(user, company_id, db):
        calls.append((user.id, company_id, db))

    monkeypatch.setattr(crm_kanban, "ensure_user_can_access_company", fake_ensure)
    db = object()
    user = SimpleNamespace(id=12)

    crm_kanban._authorize_company(user, 44, db)

    assert calls == [(12, 44, db)]
