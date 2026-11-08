from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import company_logo_media


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(company_logo_media, "COMPANY_LOGO_DIR", tmp_path)
    app = FastAPI()
    app.include_router(company_logo_media.router)
    return TestClient(app)


def test_serves_allowed_persisted_logo(tmp_path, monkeypatch):
    content = b"\x89PNG\r\n\x1a\nlogo"
    (tmp_path / "company_1_logo.png").write_bytes(content)
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/media/logos/company_1_logo.png")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=604800"


def test_rejects_invalid_or_missing_logo_paths(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    assert client.get("/media/logos/missing.png").status_code == 404
    assert client.get("/media/logos/not-an-image.txt").status_code == 400
    assert client.get("/media/logos/%2e%2e%2fsecret.png").status_code in {400, 404}
