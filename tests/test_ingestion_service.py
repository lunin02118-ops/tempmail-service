import json

from app.config import AppSettings
from app.db import initialize_database
from app.repositories.aliases import AliasRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.services.ingestion_service import ingest_gmail_message


class FakeTelegramClient:
    def __init__(self):
        self.calls = []

    def send_message(self, chat_id: str, text: str) -> dict:
        self.calls.append({"chat_id": chat_id, "text": text})
        return {"ok": True, "result": {"message_id": 999}}


class FakeTelegramClientError:
    def send_message(self, chat_id: str, text: str) -> dict:
        raise AssertionError("telegram should not be called")



def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    return AppSettings.from_env()



def sample_gmail_message():
    return {
        "id": "gmail-42",
        "threadId": "thread-42",
        "payload": {
            "headers": [
                {"name": "Delivered-To", "value": "route1@example.com"},
                {"name": "From", "value": "GitHub <notifications@github.com>"},
                {"name": "Subject", "value": "[repo] Build failed"},
                {"name": "Date", "value": "Tue, 22 Apr 2026 12:00:00 +0000"},
                {"name": "Message-Id", "value": "<msg-42@example.com>"},
            ],
            "body": {"data": "QnVpbGQgZmFpbGVk"},
        },
    }



def test_ingest_gmail_message_stores_and_dispatches(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    alias_repo = AliasRepository(settings)
    alias_repo.create_alias("route1", "route1@example.com", "555")
    message_repo = InboundMessageRepository(settings)
    telegram = FakeTelegramClient()

    result = ingest_gmail_message(
        settings=settings,
        gmail_message=sample_gmail_message(),
        alias_repo=alias_repo,
        message_repo=message_repo,
        telegram_client=telegram,
    )

    assert result["status"] == "delivered"
    assert result["telegram_chat_id"] == "555"
    stored = message_repo.get_by_gmail_message_id("gmail-42")
    assert stored is not None
    assert stored["subject"] == "[repo] Build failed"
    assert telegram.calls
    assert "Build failed" in telegram.calls[0]["text"]



def test_ingest_gmail_message_skips_when_alias_not_mapped(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    alias_repo = AliasRepository(settings)
    message_repo = InboundMessageRepository(settings)

    result = ingest_gmail_message(
        settings=settings,
        gmail_message=sample_gmail_message(),
        alias_repo=alias_repo,
        message_repo=message_repo,
        telegram_client=FakeTelegramClientError(),
    )

    assert result["status"] == "no-route"
    stored = message_repo.get_by_gmail_message_id("gmail-42")
    assert stored is not None
    assert stored["parse_status"] == "no-route"
