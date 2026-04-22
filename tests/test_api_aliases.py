from fastapi.testclient import TestClient

from app.main import create_app


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / 'client_secret.json'))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / 'token.json'))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")


def test_create_alias_endpoint_creates_alias(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/aliases",
        json={"telegram_chat_id": "12345", "description": "github inbox"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["telegram_chat_id"] == "12345"
    assert payload["alias_email"].endswith("@example.com")
    assert len(payload["alias_local_part"]) == 8


def test_list_aliases_endpoint_returns_created_aliases(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    client.post("/aliases", json={"telegram_chat_id": "12345"})
    response = client.get("/aliases")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["telegram_chat_id"] == "12345"
