import importlib

import httpx

from a2wsgi import ASGIMiddleware

from shorturl.api import create_app
from shorturl.settings import Settings


def test_wsgi_adapter_creates_and_redirects(tmp_path):
    application = ASGIMiddleware(create_app(Settings(database_path=tmp_path / "links.sqlite3")))
    transport = httpx.WSGITransport(app=application)
    with httpx.Client(transport=transport, base_url="http://localhost:8000") as client:
        created = client.post("/api/links", json={"url": "https://example.org/wsgi"})
        assert created.status_code == 201
        code = created.json()["code"]
        redirect = client.get(f"/{code}", follow_redirects=False)
        assert redirect.status_code == 302
        assert redirect.headers["location"] == "https://example.org/wsgi"
        stats = client.get(f"/api/links/{code}/stats")
        assert stats.json()["click_count"] == 1


def test_wsgi_entrypoint_starts_loop_on_first_request(tmp_path, monkeypatch):
    from shorturl import api, wsgi

    monkeypatch.setattr(api, "app", create_app(Settings(database_path=tmp_path / "wsgi.sqlite3")))
    importlib.reload(wsgi)
    assert wsgi._adapter is None

    transport = httpx.WSGITransport(app=wsgi.application)
    with httpx.Client(transport=transport, base_url="http://localhost:8000") as client:
        assert client.get("/healthz").json() == {"status": "ok"}
    assert isinstance(wsgi._adapter, ASGIMiddleware)
