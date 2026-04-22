from __future__ import annotations

import json

from app.config import AppSettings
from app.repositories.aliases import AliasRepository
from app.repositories.deliveries import DeliveryRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.services.parser_service import decode_gmail_body, extract_delivered_alias, flatten_headers
from app.services.routing_service import resolve_chat_id_for_alias


def format_telegram_message(payload: dict[str, str | None]) -> str:
    subject = payload.get("subject") or "(no subject)"
    from_address = payload.get("from_address") or "unknown sender"
    alias_email = payload.get("alias_email") or "unknown alias"
    body = (payload.get("body_text") or "").strip() or "(empty body)"
    return (
        f"New email for {alias_email}\n"
        f"From: {from_address}\n"
        f"Subject: {subject}\n\n"
        f"{body}"
    )


def ingest_gmail_message(
    settings: AppSettings,
    gmail_message: dict,
    alias_repo: AliasRepository,
    message_repo: InboundMessageRepository,
    telegram_client,
) -> dict[str, str | int | None]:
    gmail_message_id = str(gmail_message.get("id"))
    existing = message_repo.get_by_gmail_message_id(gmail_message_id)
    if existing is not None and existing["parse_status"] == "delivered":
        return {
            "status": "delivered",
            "inbound_message_id": int(existing["id"]),
            "telegram_chat_id": None,
        }

    headers = flatten_headers(gmail_message.get("payload", {}).get("headers", []))
    alias_email = extract_delivered_alias(headers)
    payload = {
        "gmail_message_id": gmail_message_id,
        "internet_message_id": headers.get("Message-Id"),
        "thread_id": gmail_message.get("threadId"),
        "alias_email": alias_email,
        "delivered_to": headers.get("Delivered-To"),
        "from_address": headers.get("From"),
        "subject": headers.get("Subject"),
        "received_at": headers.get("Date"),
        "body_text": decode_gmail_body(gmail_message.get("payload", {}).get("body", {}).get("data")),
        "body_html": None,
        "raw_headers_json": json.dumps(headers, ensure_ascii=False),
        "parse_status": "parsed" if alias_email else "missing-alias",
    }

    inbound_message_id = message_repo.create_message(payload)

    if not alias_email:
        message_repo.update_parse_status(inbound_message_id, "missing-alias")
        return {"status": "missing-alias", "inbound_message_id": inbound_message_id, "telegram_chat_id": None}

    telegram_chat_id = resolve_chat_id_for_alias(alias_repo, alias_email)
    if not telegram_chat_id:
        message_repo.update_parse_status(inbound_message_id, "no-route")
        return {"status": "no-route", "inbound_message_id": inbound_message_id, "telegram_chat_id": None}

    telegram_text = format_telegram_message(payload)
    delivery_repo = DeliveryRepository(settings)

    try:
        response = telegram_client.send_message(telegram_chat_id, telegram_text)
    except Exception as exc:
        delivery_repo.create_delivery(
            inbound_message_id=inbound_message_id,
            telegram_chat_id=telegram_chat_id,
            status="failed",
            error_text=str(exc),
        )
        message_repo.update_parse_status(inbound_message_id, "delivery-failed")
        raise

    if isinstance(response, dict) and response.get("ok") is False:
        error_text = str(response.get("description") or "telegram send_message returned ok=false")
        delivery_repo.create_delivery(
            inbound_message_id=inbound_message_id,
            telegram_chat_id=telegram_chat_id,
            status="failed",
            error_text=error_text,
        )
        message_repo.update_parse_status(inbound_message_id, "delivery-failed")
        raise RuntimeError(error_text)

    telegram_message_id = None
    if isinstance(response, dict):
        telegram_message_id = str(response.get("result", {}).get("message_id")) if response.get("result") else None

    delivery_repo.create_delivery(
        inbound_message_id=inbound_message_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        status="delivered",
    )
    message_repo.update_parse_status(inbound_message_id, "delivered")
    return {
        "status": "delivered",
        "inbound_message_id": inbound_message_id,
        "telegram_chat_id": telegram_chat_id,
    }
