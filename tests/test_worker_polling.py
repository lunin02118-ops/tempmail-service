from __future__ import annotations

import pytest

from app.config import AppSettings
from app.db import initialize_database
from app.repositories.aliases import AliasRepository
from app.worker import process_once


class FakeGmailClient:
    def __init__(self, message_ids: list[str], messages: dict[str, dict]) -> None:
        self.message_ids = message_ids
        self.messages = messages
        self.list_calls: list[dict] = []
        self.get_calls: list[str] = []

    def list_message_ids(self, query: str = "in:inbox", max_results: int = 10, page_token: str | None = None):
        self.list_calls.append({"query": query, "max_results": max_results, "page_token": page_token})
        return {"message_ids": list(self.message_ids), "next_page_token": None}

    def get_message(self, message_id: str) -> dict:
        self.get_calls.append(message_id)
        return self.messages[message_id]


class FakeTelegramClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_message(self, chat_id: str, text: str) -> dict:
        self.calls.append({"chat_id": chat_id, "text": text})
        return {"ok": True, "result": {"message_id": 12345}}


class FakeTelegramClientFailure:
    def send_message(self, chat_id: str, text: str) -> dict:
        raise AssertionError("telegram client should not be called")


def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    return AppSettings.from_env()


def sample_message(message_id: str, alias_email: str = "route1@example.com") -> dict:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "payload": {
            "headers": [
                {"name": "Delivered-To", "value": alias_email},
                {"name": "From", "value": "Alerts <alerts@example.com>"},
                {"name": "Subject", "value": f"Subject for {message_id}"},
                {"name": "Date", "value": "Tue, 22 Apr 2026 12:00:00 +0000"},
                {"name": "Message-Id", "value": f"<{message_id}@example.com>"},
            ],
            "body": {"data": "SGVsbG8="},
        },
    }


def test_process_once_delivers_new_messages_and_persists_cursor(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    alias_repo = AliasRepository(settings)
    alias_repo.create_alias("route1", "route1@example.com", "-5222282408")

    gmail = FakeGmailClient(
        message_ids=["gmail-2", "gmail-1"],
        messages={
            "gmail-1": sample_message("gmail-1"),
            "gmail-2": sample_message("gmail-2"),
        },
    )
    telegram = FakeTelegramClient()

    result = process_once(settings, gmail_client=gmail, telegram_client=telegram)

    assert result["processed"] == 2
    assert result["delivered"] == 2
    assert result["last_seen_gmail_message_id"] == "gmail-2"
    assert [call["chat_id"] for call in telegram.calls] == ["-5222282408", "-5222282408"]

    second_run = process_once(settings, gmail_client=gmail, telegram_client=FakeTelegramClientFailure())
    assert second_run["processed"] == 0
    assert second_run["skipped_seen"] == 1


def test_process_once_stops_after_known_message_boundary(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    alias_repo = AliasRepository(settings)
    alias_repo.create_alias("route1", "route1@example.com", "555")

    first_gmail = FakeGmailClient(
        message_ids=["gmail-3", "gmail-2", "gmail-1"],
        messages={
            "gmail-1": sample_message("gmail-1"),
            "gmail-2": sample_message("gmail-2"),
            "gmail-3": sample_message("gmail-3"),
        },
    )
    first_telegram = FakeTelegramClient()
    first_result = process_once(settings, gmail_client=first_gmail, telegram_client=first_telegram)
    assert first_result["processed"] == 3

    second_gmail = FakeGmailClient(
        message_ids=["gmail-4", "gmail-3", "gmail-2", "gmail-1"],
        messages={"gmail-4": sample_message("gmail-4")},
    )
    second_telegram = FakeTelegramClient()
    second_result = process_once(settings, gmail_client=second_gmail, telegram_client=second_telegram)

    assert second_result["processed"] == 1
    assert second_result["delivered"] == 1
    assert second_result["skipped_seen"] == 1
    assert second_gmail.get_calls == ["gmail-4"]
    assert len(second_telegram.calls) == 1


def test_process_once_requires_bot_token_when_client_not_injected(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    settings = AppSettings.from_env()
    initialize_database(settings)

    gmail = FakeGmailClient(message_ids=[], messages={})

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        process_once(settings, gmail_client=gmail)
