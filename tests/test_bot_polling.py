from __future__ import annotations

from app.config import AppSettings
from app.db import initialize_database
from app.repositories.aliases import AliasRepository
from app.repositories.app_settings import AppSettingsRepository
from app.worker import process_telegram_updates_once, TELEGRAM_LAST_UPDATE_ID_KEY


class FakeBotPollingTelegramClient:
    def __init__(self, updates: list[dict]) -> None:
        self.updates = updates
        self.get_updates_calls: list[dict] = []
        self.send_message_calls: list[dict] = []

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> dict:
        self.get_updates_calls.append({"offset": offset, "timeout": timeout})
        return {"ok": True, "result": list(self.updates)}

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> dict:
        self.send_message_calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return {"ok": True, "result": {"message_id": 9001}}


def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    return AppSettings.from_env()


def test_process_telegram_updates_once_handles_start_and_persists_offset(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    telegram = FakeBotPollingTelegramClient(
        updates=[
            {
                "update_id": 101,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 321, "type": "private"},
                    "from": {"id": 654, "is_bot": False, "first_name": "Vladimir"},
                    "text": "/start",
                },
            }
        ]
    )

    result = process_telegram_updates_once(settings, telegram_client=telegram)

    assert result == {"processed": 1, "handled": 1, "last_update_id": 101}
    assert telegram.get_updates_calls == [{"offset": None, "timeout": 0}]
    assert len(telegram.send_message_calls) == 1
    assert telegram.send_message_calls[0]["chat_id"] == "321"
    assert "Сгенерировать почту" in telegram.send_message_calls[0]["text"]
    assert telegram.send_message_calls[0]["reply_markup"]["one_time_keyboard"] is True
    assert telegram.send_message_calls[0]["reply_markup"]["is_persistent"] is False

    settings_repo = AppSettingsRepository(settings)
    assert settings_repo.get(TELEGRAM_LAST_UPDATE_ID_KEY) == "101"


def test_process_telegram_updates_once_uses_next_offset_and_creates_alias(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    initialize_database(settings)
    settings_repo = AppSettingsRepository(settings)
    settings_repo.set(TELEGRAM_LAST_UPDATE_ID_KEY, "101")

    telegram = FakeBotPollingTelegramClient(
        updates=[
            {
                "update_id": 102,
                "message": {
                    "message_id": 2,
                    "chat": {"id": 777, "type": "private"},
                    "from": {"id": 888, "is_bot": False, "first_name": "Vladimir"},
                    "text": "Сгенерировать почту",
                },
            }
        ]
    )

    result = process_telegram_updates_once(settings, telegram_client=telegram)

    assert result == {"processed": 1, "handled": 1, "last_update_id": 102}
    assert telegram.get_updates_calls == [{"offset": 102, "timeout": 0}]
    assert len(telegram.send_message_calls) == 1
    assert telegram.send_message_calls[0]["chat_id"] == "777"
    assert "Ваша почта:" in telegram.send_message_calls[0]["text"]
    assert "@example.com" in telegram.send_message_calls[0]["text"]

    alias_repo = AliasRepository(settings)
    aliases = alias_repo.list_aliases()
    assert len(aliases) == 1
    assert aliases[0]["telegram_chat_id"] == "777"
    assert aliases[0]["telegram_user_id"] == "888"
    assert settings_repo.get(TELEGRAM_LAST_UPDATE_ID_KEY) == "102"
