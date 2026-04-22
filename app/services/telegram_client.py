from __future__ import annotations

import httpx


class TelegramClient:
    def __init__(self, bot_token: str, timeout: float = 20.0) -> None:
        self._bot_token = bot_token
        self._timeout = timeout

    def _request(self, method: str, payload: dict | None = None) -> dict:
        response = httpx.post(
            f"https://api.telegram.org/bot{self._bot_token}/{method}",
            json=payload or {},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        return self._request("sendMessage", payload)

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> dict:
        payload: dict[str, int] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._request("getUpdates", payload)

    def delete_webhook(self, drop_pending_updates: bool = False) -> dict:
        return self._request("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def get_webhook_info(self) -> dict:
        return self._request("getWebhookInfo")

    def get_me(self) -> dict:
        return self._request("getMe")
