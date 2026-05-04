from __future__ import annotations

import asyncio
import base64
import json

from fastapi.testclient import TestClient

from app.config import AppSettings
from app.db import initialize_database
from app.main import create_app
from app.repositories.ai_extractions import AIExtractionRepository
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.mailboxes import MailboxRepository
from app.repositories.messages import MessageRepository
from app.services.ai_service import MessageAnalysisService
from app.services.gmail_tempmail_service import (
    GMAIL_SOURCE_PROVIDER,
    ingest_gmail_message_to_tempmail,
    parse_gmail_message_to_payload,
)
from app.worker import (
    LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY,
    process_gmail_tempmail_once,
)


def _run(coro):
    return asyncio.run(coro)


def _setup_tempmail_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("PUBLIC_MAIL_DOMAIN", "samgpt.me")
    monkeypatch.delenv("PUBLIC_MAIL_DOMAINS", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.delenv("INGEST_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_ENABLED", raising=False)
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    monkeypatch.delenv("ARCHIVE_ADMIN_TOKEN", raising=False)
    for index in range(1, 10):
        monkeypatch.delenv(f"GROQ_API_KEY_{index}", raising=False)
    monkeypatch.setenv("GMAIL_TEMPMAIL_ADDRESS", "17lunin021189@gmail.com")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _sample_gmail_message(message_id: str = "gmail-1", subject: str = "Your verification code is 482931") -> dict:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": ["INBOX"],
        "internalDate": "1700000000000",
        "snippet": "Use the code to confirm your sign-in.",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Acme <noreply@acme.example>"},
                {"name": "To", "value": "17lunin021189@gmail.com"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Tue, 22 Apr 2026 12:00:00 +0000"},
                {"name": "Message-Id", "value": f"<{message_id}@acme.example>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": _b64("Your verification code is 482931. It expires in 10 minutes."),
                    },
                },
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": _b64("<p>Your verification code is <strong>482931</strong>.</p>"),
                    },
                },
            ],
        },
    }


class FakeGmailClient:
    def __init__(self, message_ids: list[str], messages: dict[str, dict]) -> None:
        self.message_ids = list(message_ids)
        self.messages = messages

    def list_message_ids(self, query: str = "in:inbox", max_results: int = 10, page_token: str | None = None):
        return {"message_ids": list(self.message_ids), "next_page_token": None}

    def get_message(self, message_id: str) -> dict:
        return self.messages[message_id]


def test_parse_gmail_message_to_payload_extracts_text_html_and_metadata():
    payload = parse_gmail_message_to_payload(_sample_gmail_message(), "17lunin021189@gmail.com")

    assert payload["provider_message_id"] == "gmail-1"
    assert payload["from_address"] == "Acme <noreply@acme.example>"
    assert payload["to_address"] == "17lunin021189@gmail.com"
    assert payload["subject"] == "Your verification code is 482931"
    assert "482931" in (payload["body_text"] or "")
    assert "<strong>482931</strong>" in (payload["body_html"] or "")
    assert payload["received_at"] is not None
    raw_payload = json.loads(payload["raw_payload_json"])
    assert raw_payload["gmail_message_id"] == "gmail-1"
    assert raw_payload["headers"]["Subject"] == "Your verification code is 482931"


def test_ingest_gmail_message_to_tempmail_creates_public_mailbox_and_runs_analysis(tmp_path, monkeypatch):
    _setup_tempmail_env(tmp_path, monkeypatch)
    settings = AppSettings.from_env()
    initialize_database(settings)

    mailbox_repo = MailboxRepository(settings)
    message_repo = MessageRepository(settings)
    ai_repo = AIExtractionRepository(settings)
    analysis_service = MessageAnalysisService(settings)

    result = _run(
        ingest_gmail_message_to_tempmail(
            settings=settings,
            gmail_message=_sample_gmail_message(),
            mailbox_repo=mailbox_repo,
            message_repo=message_repo,
            ai_repo=ai_repo,
            analysis_service=analysis_service,
            allow_remote_ai=False,
        )
    )

    assert result["status"] == "delivered"
    assert result["mailbox_address"] == "17lunin021189@gmail.com"

    public_mailboxes = mailbox_repo.list_public()
    assert len(public_mailboxes) == 1
    assert public_mailboxes[0]["visibility"] == "public"

    inbox = message_repo.list_public_inbox()
    assert len(inbox) == 1
    assert inbox[0]["mailbox_address"] == "17lunin021189@gmail.com"

    codes = message_repo.list_public_codes()
    assert len(codes) == 1
    assert codes[0]["otp_code"] == "482931"

    extraction = ai_repo.get_by_message_id(int(result["message_id"]))
    assert extraction is not None
    assert extraction["provider"] == "deterministic"


def test_ingest_gmail_message_to_tempmail_is_idempotent(tmp_path, monkeypatch):
    _setup_tempmail_env(tmp_path, monkeypatch)
    settings = AppSettings.from_env()
    initialize_database(settings)

    mailbox_repo = MailboxRepository(settings)
    message_repo = MessageRepository(settings)
    ai_repo = AIExtractionRepository(settings)
    analysis_service = MessageAnalysisService(settings)

    first = _run(
        ingest_gmail_message_to_tempmail(
            settings=settings,
            gmail_message=_sample_gmail_message(),
            mailbox_repo=mailbox_repo,
            message_repo=message_repo,
            ai_repo=ai_repo,
            analysis_service=analysis_service,
            allow_remote_ai=False,
        )
    )
    second = _run(
        ingest_gmail_message_to_tempmail(
            settings=settings,
            gmail_message=_sample_gmail_message(),
            mailbox_repo=mailbox_repo,
            message_repo=message_repo,
            ai_repo=ai_repo,
            analysis_service=analysis_service,
            allow_remote_ai=False,
        )
    )

    assert first["message_id"] == second["message_id"]
    assert len(message_repo.list_public_inbox()) == 1


def test_process_gmail_tempmail_once_bootstrap_then_processes_only_new(tmp_path, monkeypatch):
    _setup_tempmail_env(tmp_path, monkeypatch)
    settings = AppSettings.from_env()
    initialize_database(settings)

    messages = {
        "gmail-2": _sample_gmail_message("gmail-2", "Code 222222"),
        "gmail-1": _sample_gmail_message("gmail-1", "Code 111111"),
    }
    fake = FakeGmailClient(message_ids=["gmail-2", "gmail-1"], messages=messages)

    bootstrap = process_gmail_tempmail_once(settings, gmail_client=fake, allow_remote_ai=False)
    assert bootstrap["bootstrap"] is True
    assert bootstrap["processed"] == 0
    assert bootstrap["last_seen_gmail_tempmail_message_id"] == "gmail-2"

    settings_repo = AppSettingsRepository(settings)
    assert settings_repo.get(LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY) == "gmail-2"

    messages["gmail-3"] = _sample_gmail_message("gmail-3", "Code 333333")
    fake.message_ids = ["gmail-3", "gmail-2", "gmail-1"]

    second = process_gmail_tempmail_once(settings, gmail_client=fake, allow_remote_ai=False)
    assert second["bootstrap"] is False
    assert second["processed"] == 1
    assert second["skipped_seen"] == 1
    assert second["last_seen_gmail_tempmail_message_id"] == "gmail-3"

    third = process_gmail_tempmail_once(settings, gmail_client=fake, allow_remote_ai=False)
    assert third["processed"] == 0
    assert third["skipped_seen"] == 1


def test_process_gmail_tempmail_once_truncates_large_backlogs(tmp_path, monkeypatch):
    _setup_tempmail_env(tmp_path, monkeypatch)
    settings = AppSettings.from_env()
    initialize_database(settings)

    settings_repo = AppSettingsRepository(settings)
    settings_repo.set(LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY, "gmail-seen")

    backlog_ids = [f"gmail-{i:03d}" for i in range(1, 11)]
    messages = {mid: _sample_gmail_message(mid, f"Code {mid}") for mid in backlog_ids}
    fake = FakeGmailClient(message_ids=list(reversed(backlog_ids)) + ["gmail-seen"], messages=messages)

    result = process_gmail_tempmail_once(
        settings, gmail_client=fake, max_messages=3, allow_remote_ai=False
    )

    assert result["processed"] == 3
    assert result["truncated"] is True
    assert result["last_seen_gmail_tempmail_message_id"] == "gmail-010"


def test_public_endpoints_serve_ingested_gmail_messages(tmp_path, monkeypatch):
    _setup_tempmail_env(tmp_path, monkeypatch)
    settings = AppSettings.from_env()
    initialize_database(settings)

    mailbox_repo = MailboxRepository(settings)
    message_repo = MessageRepository(settings)
    ai_repo = AIExtractionRepository(settings)
    analysis_service = MessageAnalysisService(settings)
    _run(
        ingest_gmail_message_to_tempmail(
            settings=settings,
            gmail_message=_sample_gmail_message(),
            mailbox_repo=mailbox_repo,
            message_repo=message_repo,
            ai_repo=ai_repo,
            analysis_service=analysis_service,
            allow_remote_ai=False,
        )
    )

    client = TestClient(create_app())

    config = client.get("/client-config").json()
    assert config["shared_inbox_enabled"] is True
    assert config["shared_inbox_address"] == "17lunin021189@gmail.com"

    public_mailboxes = client.get("/public/mailboxes").json()
    assert any(box["address"] == "17lunin021189@gmail.com" for box in public_mailboxes)

    public_codes = client.get("/public/codes").json()
    assert public_codes
    assert public_codes[0]["otp_code"] == "482931"

    detail = client.get(f"/public/messages/{public_codes[0]['id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["source_provider"] == GMAIL_SOURCE_PROVIDER
    assert detail_payload["mailbox_address"] == "17lunin021189@gmail.com"
