from app.config import AppSettings
from app.db import initialize_database
from app.main import create_app


def test_initialize_database_creates_core_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))

    settings = AppSettings.from_env()
    initialize_database(settings)

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    finally:
        conn.close()

    assert {"aliases", "inbound_messages", "deliveries", "app_settings"}.issubset(table_names)


def test_health_endpoint_returns_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))

    app = create_app()

    route = next(route for route in app.router.routes if getattr(route, "path", None) == "/health")
    response = route.endpoint()

    assert response == {"status": "ok", "service": "samgpt-tempmail"}
