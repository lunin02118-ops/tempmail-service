from fastapi.testclient import TestClient

from app.main import create_app


class RecordingTelegramClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> dict:
        self.calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return {"ok": True, "result": {"message_id": 777}}


def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / 'client_secret.json'))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / 'token.json'))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")


def build_client(tmp_path, monkeypatch):
    setup_env(tmp_path, monkeypatch)
    telegram = RecordingTelegramClient()
    app = create_app(telegram_client=telegram)
    return TestClient(app), telegram


def test_start_command_returns_keyboard(tmp_path, monkeypatch):
    client, telegram = build_client(tmp_path, monkeypatch)

    response = client.post(
        "/telegram/webhook",
        json={
            "message": {
                "message_id": 1,
                "chat": {"id": 321, "type": "private"},
                "from": {"id": 321, "is_bot": False, "first_name": "Vladimir"},
                "text": "/start",
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(telegram.calls) == 1
    assert telegram.calls[0]["chat_id"] == "321"
    assert "Сгенерировать почту" in telegram.calls[0]["text"]
    assert telegram.calls[0]["reply_markup"]["keyboard"][0][0]["text"] == "Сгенерировать почту"
    assert telegram.calls[0]["reply_markup"]["one_time_keyboard"] is True
    assert telegram.calls[0]["reply_markup"]["is_persistent"] is False


def test_generate_alias_button_creates_alias_and_returns_email(tmp_path, monkeypatch):
    client, telegram = build_client(tmp_path, monkeypatch)

    response = client.post(
        "/telegram/webhook",
        json={
            "message": {
                "message_id": 2,
                "chat": {"id": 321, "type": "private"},
                "from": {"id": 321, "is_bot": False, "first_name": "Vladimir"},
                "text": "Сгенерировать почту",
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(telegram.calls) == 1
    assert telegram.calls[0]["chat_id"] == "321"
    assert "@example.com" in telegram.calls[0]["text"]
    assert "Ваша почта" in telegram.calls[0]["text"]

    aliases = client.get("/aliases")
    payload = aliases.json()
    assert len(payload) == 1
    assert payload[0]["telegram_chat_id"] == "321"
    assert payload[0]["telegram_user_id"] == "321"


def test_unknown_message_keeps_keyboard_and_guides_user(tmp_path, monkeypatch):
    client, telegram = build_client(tmp_path, monkeypatch)

    response = client.post(
        "/telegram/webhook",
        json={
            "message": {
                "message_id": 3,
                "chat": {"id": 321, "type": "private"},
                "from": {"id": 321, "is_bot": False, "first_name": "Vladimir"},
                "text": "Привет",
            }
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(telegram.calls) == 1
    assert "Сгенерировать почту" in telegram.calls[0]["text"]
    assert telegram.calls[0]["reply_markup"]["keyboard"][0][0]["text"] == "Сгенерировать почту"
    assert telegram.calls[0]["reply_markup"]["one_time_keyboard"] is True
    assert telegram.calls[0]["reply_markup"]["is_persistent"] is False
