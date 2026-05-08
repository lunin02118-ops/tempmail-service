from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import AppSettings


GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


class GmailClient:
    def __init__(self, settings: AppSettings, timeout: float = 30.0, persistent: bool = False) -> None:
        self._settings = settings
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout) if persistent else None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> "GmailClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _load_token_payload(self) -> dict:
        return json.loads(Path(self._settings.gmail_token_path).read_text())

    def _write_token_payload(self, payload: dict) -> None:
        Path(self._settings.gmail_token_path).write_text(json.dumps(payload), encoding="utf-8")

    def _load_access_token(self) -> str:
        data = self._load_token_payload()
        access_token = data.get("access_token") or data.get("token")
        if not access_token:
            raise ValueError("gmail token file does not contain access_token")
        return str(access_token)

    def refresh_access_token(self) -> str:
        token_payload = self._load_token_payload()
        refresh_token = token_payload.get("refresh_token")
        if not refresh_token:
            raise ValueError("gmail token file does not contain refresh_token")

        client_payload = json.loads(Path(self._settings.gmail_client_secret_path).read_text())
        client_info = client_payload.get("installed") or client_payload.get("web") or {}
        client_id = client_info.get("client_id")
        client_secret = client_info.get("client_secret")
        token_uri = client_info.get("token_uri", "https://oauth2.googleapis.com/token")
        if not client_id or not client_secret:
            raise ValueError("gmail client secret file does not contain client_id/client_secret")

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if self._client is not None:
            response = self._client.post(token_uri, data=data)
        else:
            response = httpx.post(token_uri, data=data, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise ValueError("token refresh response does not contain access_token")

        token_payload["access_token"] = access_token
        token_payload["token"] = access_token
        if payload.get("refresh_token"):
            token_payload["refresh_token"] = payload["refresh_token"]
        self._write_token_payload(token_payload)
        return str(access_token)

    def _headers(self) -> dict[str, str]:
        try:
            access_token = self._load_access_token()
        except ValueError:
            access_token = self.refresh_access_token()
        return {"Authorization": f"Bearer {access_token}"}

    def _get_with_auto_refresh(self, url: str, params: dict) -> dict:
        headers = self._headers()
        response = self._get(url, headers=headers, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code != 401:
                raise
            access_token = self.refresh_access_token()
            headers = {"Authorization": f"Bearer {access_token}"}
            response = self._get(url, headers=headers, params=params)
            response.raise_for_status()
        return response.json()

    def _get(self, url: str, *, headers: dict[str, str], params: dict) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, headers=headers, params=params)
        return httpx.get(url, headers=headers, params=params, timeout=self._timeout)

    def list_message_ids(
        self,
        query: str = "in:inbox",
        max_results: int = 10,
        page_token: str | None = None,
    ) -> dict[str, str | list[str] | None]:
        params = {"q": query, "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        payload = self._get_with_auto_refresh(GMAIL_MESSAGES_URL, params)
        return {
            "message_ids": [item["id"] for item in payload.get("messages", []) if item.get("id")],
            "next_page_token": payload.get("nextPageToken"),
        }

    def get_message(self, message_id: str) -> dict:
        return self._get_with_auto_refresh(
            f"{GMAIL_MESSAGES_URL}/{message_id}",
            {"format": "full"},
        )
