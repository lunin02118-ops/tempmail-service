import sqlite3

from app.config import AppSettings
from app.db import initialize_database, resolve_sqlite_path
from app.repositories.aliases import AliasRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.services.alias_service import normalize_alias_email
from app.services.routing_service import resolve_chat_id_for_alias


def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    return AppSettings.from_env()


def test_alias_repository_creates_and_fetches_alias(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    repo = AliasRepository(settings)

    alias_email = normalize_alias_email("abc123", "example.com")
    alias_id = repo.create_alias(
        alias_local_part="abc123",
        alias_email=alias_email,
        telegram_chat_id="123456",
        description="test alias",
    )

    row = repo.get_by_alias_email(alias_email)

    assert alias_id > 0
    assert row is not None
    assert row["alias_email"] == alias_email
    assert row["telegram_chat_id"] == "123456"
    assert row["is_active"] == 1


def test_resolve_chat_id_for_alias_returns_chat_id_only_for_active_alias(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    repo = AliasRepository(settings)

    repo.create_alias("live1", "live1@example.com", "777")
    inactive_id = repo.create_alias("dead1", "dead1@example.com", "888")

    db_path = resolve_sqlite_path(settings.database_url)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE aliases SET is_active = 0 WHERE id = ?", (inactive_id,))
        conn.commit()
    finally:
        conn.close()

    assert resolve_chat_id_for_alias(repo, "live1@example.com") == "777"
    assert resolve_chat_id_for_alias(repo, "dead1@example.com") is None
    assert resolve_chat_id_for_alias(repo, "missing@example.com") is None


def test_inbound_message_repository_stores_message_once(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    repo = InboundMessageRepository(settings)

    payload = {
        "gmail_message_id": "gmail-1",
        "internet_message_id": "<m1@example.com>",
        "thread_id": "thread-1",
        "alias_email": "abc123@example.com",
        "delivered_to": "abc123@example.com",
        "from_address": "noreply@github.com",
        "subject": "Test subject",
        "received_at": "2026-04-22T12:00:00Z",
        "body_text": "hello",
        "body_html": "<p>hello</p>",
        "raw_headers_json": '{"To": "abc123@example.com"}',
        "parse_status": "parsed",
    }

    first_id = repo.create_message(payload)
    second_id = repo.create_message(payload)

    assert first_id > 0
    assert second_id == first_id

    stored = repo.get_by_gmail_message_id("gmail-1")
    assert stored is not None
    assert stored["subject"] == "Test subject"
    assert stored["alias_email"] == "abc123@example.com"
