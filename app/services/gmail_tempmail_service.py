from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime

from app.config import AppSettings
from app.repositories.ai_extractions import AIExtractionRepository
from app.repositories.mailboxes import MailboxRepository
from app.repositories.messages import MessageRepository
from app.services.ai_service import MessageAnalysisService
from app.services.parser_service import flatten_headers
from app.services.text_encoding import (
    EMAIL_BODY_MAX_CHARS,
    normalize_email_content,
    sanitize_email_header,
    sanitize_json_payload,
    sanitize_raw_payload_json,
)


logger = logging.getLogger(__name__)

GMAIL_SOURCE_PROVIDER = "gmail"


def _decode_base64url(data: str | None) -> bytes:
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8"))
    except (ValueError, TypeError):
        return b""


def _decode_part_body(data: str | None) -> str:
    if not data:
        return ""
    raw = _decode_base64url(data)
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")


def _walk_parts(payload: dict | None):
    if not payload:
        return
    yield payload
    for part in payload.get("parts") or []:
        yield from _walk_parts(part)


def _extract_bodies(payload: dict | None) -> tuple[str, str, bool]:
    body_text_chunks: list[str] = []
    body_html_chunks: list[str] = []
    has_attachments = False

    for part in _walk_parts(payload):
        mime_type = str(part.get("mimeType") or "").lower()
        filename = str(part.get("filename") or "").strip()
        body = part.get("body") or {}
        data = body.get("data")

        if filename:
            has_attachments = True

        if not data:
            continue

        if mime_type == "text/plain":
            body_text_chunks.append(_decode_part_body(data))
        elif mime_type == "text/html":
            body_html_chunks.append(_decode_part_body(data))
        elif mime_type.startswith("text/") and not body_text_chunks and not body_html_chunks:
            body_text_chunks.append(_decode_part_body(data))

    body_text = "\n\n".join(chunk for chunk in body_text_chunks if chunk).strip()
    body_html = "\n\n".join(chunk for chunk in body_html_chunks if chunk).strip()
    return body_text, body_html, has_attachments


def _parse_received_at(date_header: str | None) -> datetime | None:
    if not date_header:
        return None
    try:
        return parsedate_to_datetime(date_header)
    except (TypeError, ValueError, IndexError):
        return None


def parse_gmail_message_to_payload(gmail_message: dict, fallback_to_address: str) -> dict[str, object]:
    payload = gmail_message.get("payload") or {}
    headers = {
        str(name): sanitize_email_header(str(value)) or ""
        for name, value in flatten_headers(payload.get("headers") or []).items()
    }
    body_text, body_html, has_attachments = _extract_bodies(payload)

    raw_payload = {
        "gmail_message_id": gmail_message.get("id"),
        "thread_id": gmail_message.get("threadId"),
        "label_ids": gmail_message.get("labelIds") or [],
        "internal_date": gmail_message.get("internalDate"),
        "snippet": sanitize_email_header(str(gmail_message.get("snippet") or "")) or None,
        "headers": headers,
    }
    to_address = (sanitize_email_header(headers.get("To") or fallback_to_address) or fallback_to_address).strip().lower()
    raw_payload_json = sanitize_raw_payload_json(
        json.dumps(sanitize_json_payload(raw_payload), ensure_ascii=False),
    )

    return {
        "provider_message_id": sanitize_email_header(str(gmail_message.get("id") or "")) or "",
        "internet_message_id": headers.get("Message-Id") or headers.get("Message-ID"),
        "from_address": sanitize_email_header(headers.get("From") or "") or None,
        "to_address": to_address or fallback_to_address,
        "subject": sanitize_email_header(headers.get("Subject") or "") or None,
        "received_at": _parse_received_at(headers.get("Date")),
        "body_text": normalize_email_content(body_text, max_chars=EMAIL_BODY_MAX_CHARS) or None,
        "body_html": normalize_email_content(body_html, max_chars=EMAIL_BODY_MAX_CHARS) or None,
        "raw_payload_json": raw_payload_json,
        "has_attachments": bool(has_attachments),
    }


async def ingest_gmail_message_to_tempmail(
    *,
    settings: AppSettings,
    gmail_message: dict,
    mailbox_repo: MailboxRepository,
    message_repo: MessageRepository,
    ai_repo: AIExtractionRepository,
    analysis_service: MessageAnalysisService,
    allow_remote_ai: bool = True,
) -> dict[str, object]:
    if not settings.gmail_tempmail_address:
        raise ValueError("GMAIL_TEMPMAIL_ADDRESS is not configured")

    mailbox = mailbox_repo.get_or_create_service_mailbox(
        address=settings.gmail_tempmail_address,
        description="Mirrored from Gmail",
    )

    parsed = parse_gmail_message_to_payload(gmail_message, settings.gmail_tempmail_address)

    message_id = message_repo.create_ingested_message(
        mailbox_id=int(mailbox["id"]),
        source_provider=GMAIL_SOURCE_PROVIDER,
        provider_message_id=parsed["provider_message_id"] or None,
        internet_message_id=parsed["internet_message_id"],
        from_address=parsed["from_address"],
        to_address=parsed["to_address"],
        subject=parsed["subject"],
        received_at=parsed["received_at"],
        body_text=parsed["body_text"],
        body_html=parsed["body_html"],
        raw_payload_json=parsed["raw_payload_json"],
        has_attachments=parsed["has_attachments"],
    )
    mailbox_repo.touch_last_seen(int(mailbox["id"]))

    extraction_status = "skipped"
    if ai_repo.get_by_message_id(message_id) is None:
        message_for_analysis = {
            "from_address": parsed["from_address"],
            "subject": parsed["subject"],
            "body_text": parsed["body_text"],
            "body_html": parsed["body_html"],
            "mailbox_address": str(mailbox["address"]),
        }
        try:
            analysis_payload = await analysis_service.analyze_message(
                message_for_analysis,
                allow_remote=allow_remote_ai,
            )
            ai_repo.upsert(message_id, analysis_payload)
            extraction_status = "analyzed"
        except Exception:
            logger.exception("analysis failed for gmail message_id=%s", message_id)
            try:
                fallback = analysis_service.analyze_deterministically(message_for_analysis)
                ai_repo.upsert(message_id, fallback)
                extraction_status = "analyzed_deterministic_fallback"
            except Exception:
                logger.exception("deterministic fallback failed for gmail message_id=%s", message_id)
                extraction_status = "failed"

    return {
        "status": "delivered",
        "mailbox_id": int(mailbox["id"]),
        "mailbox_address": str(mailbox["address"]),
        "message_id": message_id,
        "extraction_status": extraction_status,
    }
