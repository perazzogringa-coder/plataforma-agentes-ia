"""Ensure periodic Agents SDK tasks are registered by Celery workers."""
import os


os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test@127.0.0.1:65432/celery_test")


def test_agents_sdk_periodic_tasks_are_registered():
    from backend.worker.celery_app import app

    app.loader.import_task_module("backend.agents_sdk.tasks.celery_tasks")

    assert "backend.agents_sdk.tasks.celery_tasks" in app.conf.include
    assert "agents_sdk.refresh_all_companies_slots" in app.tasks
    assert "agents_sdk.cleanup_expired_slots" in app.tasks
