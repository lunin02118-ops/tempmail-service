from __future__ import annotations

import json

from app.config import AppSettings
from app.services.gmail_client import GmailClient


def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    return AppSettings.from_env()


def test_load_access_token_accepts_google_auth_token_field(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    settings.gmail_token_path.write_text(json.dumps({"token": "ya29.test-token"}), encoding="utf-8")

    client = GmailClient(settings)

    assert client._load_access_token() == "ya29.test-token"
