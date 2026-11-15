import hashlib
import hmac
import os

import pytest
from fastapi import HTTPException


os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.routes.waha_routes import _validate_waha_webhook_hmac  # noqa: E402
from backend.routes.webhook import configure_waha_webhooks_completely  # noqa: E402


class _FakeWahaClient:
    def __init__(self):
        self.calls = []

    def _request(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


def _headers(secret: str, body: bytes):
    return {
        "X-Webhook-Hmac-Algorithm": "sha512",
        "X-Webhook-Hmac": hmac.new(
            secret.encode("utf-8"), body, hashlib.sha512
        ).hexdigest(),
    }


def test_waha_webhook_accepts_valid_sha512_signature(monkeypatch):
    secret = "test-hmac-secret"
    body = b'{"event":"message","session":"session-test"}'
    monkeypatch.setenv("WAHA_WEBHOOK_HMAC_KEY", secret)

    _validate_waha_webhook_hmac(body, _headers(secret, body))


def test_waha_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("WAHA_WEBHOOK_HMAC_KEY", "test-hmac-secret")

    with pytest.raises(HTTPException) as error:
        _validate_waha_webhook_hmac(
            b'{"event":"message"}',
            {
                "X-Webhook-Hmac-Algorithm": "sha512",
                "X-Webhook-Hmac": "invalid",
            },
        )

    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Webhook-Hmac-Algorithm": "sha512"},
        {"X-Webhook-Hmac": "missing-algorithm"},
        {
            "X-Webhook-Hmac-Algorithm": "sha256",
            "X-Webhook-Hmac": "not-used",
        },
    ],
)
def test_waha_webhook_rejects_missing_or_non_sha512_signature(monkeypatch, headers):
    monkeypatch.setenv("WAHA_WEBHOOK_HMAC_KEY", "test-hmac-secret")

    with pytest.raises(HTTPException) as error:
        _validate_waha_webhook_hmac(b'{"event":"message"}', headers)

    assert error.value.status_code == 401


def test_waha_webhook_fails_closed_without_hmac_key(monkeypatch):
    monkeypatch.delenv("WAHA_WEBHOOK_HMAC_KEY", raising=False)

    with pytest.raises(HTTPException) as error:
        _validate_waha_webhook_hmac(b"{}", {})

    assert error.value.status_code == 503


def test_waha_webhook_configuration_includes_hmac_only_when_configured(monkeypatch):
    client = _FakeWahaClient()
    monkeypatch.setenv("WAHA_WEBHOOK_URL", "https://example.test/webhook/waha/callback")
    monkeypatch.setenv("WAHA_WEBHOOK_HMAC_KEY", "test-hmac-secret")

    assert configure_waha_webhooks_completely(client, "session-test") is True

    payload = client.calls[0]["json"]
    webhook = payload["config"]["webhooks"][0]
    assert webhook["url"] == "https://example.test/webhook/waha/callback"
    assert webhook["hmac"] == {"key": "test-hmac-secret"}

    client = _FakeWahaClient()
    monkeypatch.delenv("WAHA_WEBHOOK_HMAC_KEY", raising=False)
    assert configure_waha_webhooks_completely(client, "session-test") is True
    assert "hmac" not in client.calls[0]["json"]["config"]["webhooks"][0]
