from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
import sqlite3

from fastapi.testclient import TestClient
import pytest

from clew.api import create_app
from clew.settings import Settings
from clew.storage import SQLiteStore


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_path=tmp_path / "links.sqlite3"))
    with TestClient(app) as test_client:
        yield test_client


def create_link(client, url="https://example.org/a?x=1"):
    response = client.post("/api/links", json={"url": url})
    assert response.status_code == 201
    return response.json()


def test_create_redirect_and_analytics_survive_restart(client, tmp_path):
    link = create_link(client)
    assert re.fullmatch(r"[A-Za-z0-9]{10}", link["code"])
    assert link["short_url"] == f"http://localhost:8000/{link['code']}"
    initial_stats = client.get(f"/api/links/{link['code']}/stats")
    assert initial_stats.headers["cache-control"] == "no-store"
    assert initial_stats.json()["click_count"] == 0
    assert initial_stats.json()["last_clicked_at"] is None
    assert initial_stats.json()["recent_clicks"] == []
    assert client.get(f"/{link['code']}", follow_redirects=False).headers["location"] == link["url"]

    stats = client.get(f"/api/links/{link['code']}/stats").json()
    assert stats["click_count"] == 1
    assert stats["last_clicked_at"] == stats["recent_clicks"][0]
    assert datetime.fromisoformat(stats["last_clicked_at"].replace("Z", "+00:00"))

    # HEAD checks the destination without recording a click.
    head = client.head(f"/{link['code']}", follow_redirects=False)
    assert head.status_code == 302
    assert head.headers["location"] == link["url"]
    assert client.get(f"/api/links/{link['code']}/stats").json()["click_count"] == 1

    restarted = TestClient(create_app(Settings(database_path=tmp_path / "links.sqlite3")))
    with restarted:
        assert restarted.get(f"/{link['code']}", follow_redirects=False).status_code == 302
        assert restarted.get(f"/api/links/{link['code']}/stats").json()["click_count"] == 2


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/file",
        "javascript:alert(1)",
        "https://user:pass@example.org/",
        "https://example.org/with space",
        "https://example.org/\nheader:evil",
        "not-a-url",
        "https://",
        "https://example.org/" + "a" * 2048,
        "https://example.org/" + "ü" * 400,
        123,
    ],
)
def test_invalid_urls_are_rejected(client, url):
    response = client.post("/api/links", json={"url": url})
    assert response.status_code == 422


def test_missing_links_return_404(client):
    assert client.get("/nonexistent", follow_redirects=False).status_code == 404
    assert client.head("/nonexistent").status_code == 404
    assert client.get("/api/links/nonexistent/stats").status_code == 404


def test_international_url_is_normalized_for_redirect(client):
    link = create_link(client, "https://bücher.example/ümlaut")
    response = client.get(f"/{link['code']}", follow_redirects=False)
    assert response.headers["location"] == "https://xn--bcher-kva.example/%C3%BCmlaut"


def test_health_and_authentication(tmp_path):
    settings = Settings(
        database_path=tmp_path / "links.sqlite3",
        base_url="https://sho.rt",
        api_key="this-is-a-test-api-key-with-32-characters",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.post("/api/links", json={"url": "https://example.org"}).status_code == 401
        headers = {"X-API-Key": settings.api_key}
        response = client.post(
            "/api/links", json={"url": "https://example.org"}, headers=headers
        )
        assert response.status_code == 201
        link = response.json()
        assert link["short_url"].startswith("https://sho.rt/")
        assert response.headers["location"] == link["short_url"]
        assert client.get(f"/api/links/{link['code']}/stats").status_code == 401
        assert client.get(f"/api/links/{link['code']}/stats", headers=headers).status_code == 200
        assert client.get(f"/{link['code']}", follow_redirects=False).status_code == 302


def test_simultaneous_clicks_are_counted(tmp_path):
    store = SQLiteStore(tmp_path / "links.sqlite3")
    store.initialize()
    code = store.create_link("https://example.org")["code"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        destinations = list(pool.map(store.record_click, [code] * 40))
    assert destinations == ["https://example.org"] * 40
    stats = store.stats_for(code)
    assert stats["click_count"] == 40
    assert len(stats["recent_clicks"]) == 20
    with sqlite3.connect(tmp_path / "links.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM clicks").fetchone()[0] == 20


def test_code_collision_is_retried(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "links.sqlite3")
    store.initialize()
    codes = iter(["AAAAAAAAAA", "AAAAAAAAAA", "BBBBBBBBBB"])
    monkeypatch.setattr("clew.storage.new_code", lambda: next(codes))
    assert store.create_link("https://example.org/one")["code"] == "AAAAAAAAAA"
    assert store.create_link("https://example.org/two")["code"] == "BBBBBBBBBB"


def test_exhausted_codes_return_service_unavailable(client, monkeypatch):
    monkeypatch.setattr("clew.storage.new_code", lambda: "AAAAAAAAAA")
    create_link(client)
    response = client.post("/api/links", json={"url": "https://example.org/two"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Could not create link"}


@pytest.mark.parametrize(
    "base_url", ["http://example.org", "https://example.org/path", "https://exa mple.org"]
)
def test_invalid_public_configuration_is_rejected(tmp_path, base_url):
    with pytest.raises(ValueError):
        Settings(database_path=tmp_path / "links.sqlite3", base_url=base_url)


def test_renamed_environment_variables_override_existing_values(tmp_path, monkeypatch):
    old_key = "old-api-key-with-at-least-32-characters"
    new_key = "new-api-key-with-at-least-32-characters"
    monkeypatch.setenv("SHORTURL_DATABASE_PATH", str(tmp_path / "old.sqlite3"))
    monkeypatch.setenv("SHORTURL_BASE_URL", "https://old.example.org")
    monkeypatch.setenv("SHORTURL_API_KEY", old_key)

    old = Settings.from_environment()
    assert old.database_path == tmp_path / "old.sqlite3"
    assert old.base_url == "https://old.example.org"
    assert old.api_key == old_key

    monkeypatch.setenv("CLEW_DATABASE_PATH", str(tmp_path / "new.sqlite3"))
    monkeypatch.setenv("CLEW_BASE_URL", "https://new.example.org")
    monkeypatch.setenv("CLEW_API_KEY", new_key)

    renamed = Settings.from_environment()
    assert renamed.database_path == tmp_path / "new.sqlite3"
    assert renamed.base_url == "https://new.example.org"
    assert renamed.api_key == new_key
