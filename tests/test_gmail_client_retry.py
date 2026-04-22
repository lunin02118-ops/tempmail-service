from __future__ import annotations

from app.config import AppSettings
from app.services.gmail_client import GmailClient


class UnauthorizedThenOkResponse:
    def __init__(self, payload: dict, should_fail: bool = False) -> None:
        self._payload = payload
        self._should_fail = should_fail

    def raise_for_status(self) -> None:
        if self._should_fail:
            import httpx
            request = httpx.Request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)

    def json(self) -> dict:
        return self._payload


def build_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_PATH", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("DEFAULT_FROM_ALIAS_DOMAIN", "example.com")
    return AppSettings.from_env()


def test_list_message_ids_refreshes_and_retries_after_401(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, monkeypatch)
    client = GmailClient(settings)

    refresh_calls: list[str] = []
    monkeypatch.setattr(client, "_headers", lambda: {"Authorization": "Bearer old-token"})

    def fake_refresh() -> str:
        refresh_calls.append("refresh")
        return "new-token"

    monkeypatch.setattr(client, "refresh_access_token", fake_refresh)

    calls: list[dict] = []

    def fake_get(url, headers=None, params=None, timeout=30.0):
        calls.append({"url": url, "headers": headers, "params": params})
        if len(calls) == 1:
            return UnauthorizedThenOkResponse({}, should_fail=True)
        return UnauthorizedThenOkResponse({"messages": [{"id": "gmail-1"}]})

    monkeypatch.setattr("app.services.gmail_client.httpx.get", fake_get)

    result = client.list_message_ids()

    assert result == {"message_ids": ["gmail-1"], "next_page_token": None}
    assert refresh_calls == ["refresh"]
    assert len(calls) == 2
    assert calls[1]["headers"] == {"Authorization": "Bearer new-token"}
