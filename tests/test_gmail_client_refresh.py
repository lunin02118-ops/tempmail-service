from __future__ import annotations

import json

from app.config import AppSettings
from app.services.gmail_client import GmailClient


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    return AppSettings.from_env()


def test_refresh_access_token_uses_refresh_token_and_persists_new_token(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    settings.gmail_client_secret_path.write_text(
        json.dumps({
            "installed": {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }),
        encoding="utf-8",
    )
    settings.gmail_token_path.write_text(
        json.dumps({"refresh_token": "refresh-me", "token": "old-token"}),
        encoding="utf-8",
    )

    captured: dict = {}

    def fake_post(url, data=None, timeout=30.0):
        captured["url"] = url
        captured["data"] = data
        return DummyResponse({"access_token": "new-access-token"})

    monkeypatch.setattr("app.services.gmail_client.httpx.post", fake_post)
    client = GmailClient(settings)

    token = client.refresh_access_token()

    assert token == "new-access-token"
    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert captured["data"] == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-me",
        "grant_type": "refresh_token",
    }
    persisted = json.loads(settings.gmail_token_path.read_text(encoding="utf-8"))
    assert persisted["token"] == "new-access-token"
    assert persisted["refresh_token"] == "refresh-me"
