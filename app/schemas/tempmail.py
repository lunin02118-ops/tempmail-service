from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MailboxCreateRequest(BaseModel):
    description: str | None = None
    requested_local_part: str | None = Field(default=None, min_length=3, max_length=32)
    local_part_length: int = Field(default=10, ge=4, le=32)
    expires_in_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    turnstile_token: str | None = None


class MailboxResponse(BaseModel):
    id: int
    local_part: str
    domain: str
    address: str
    visibility: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None = None
    expires_at: datetime


class MailboxCreateResponse(BaseModel):
    session_token: str
    mailbox: MailboxResponse


class AIExtractionResponse(BaseModel):
    provider: str | None = None
    model: str | None = None
    status: str | None = None
    summary: str | None = None
    message_type: str | None = None
    otp_code: str | None = None
    action_required: str | None = None
    action_links: list[str] = Field(default_factory=list)
    sender_brand: str | None = None
    confidence: str | None = None
    error_text: str | None = None


class MessageSummaryResponse(BaseModel):
    id: int
    mailbox_id: int
    mailbox_address: str
    mailbox_local_part: str | None = None
    mailbox_domain: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    subject: str | None = None
    received_at: datetime
    has_attachments: bool
    is_unread: bool
    ai_summary: str | None = None
    otp_code: str | None = None
    action_required: str | None = None
    sender_brand: str | None = None
    ai_status: str | None = None


class MessageDetailResponse(MessageSummaryResponse):
    source_provider: str
    provider_message_id: str | None = None
    internet_message_id: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    raw_payload_json: str | None = None
    analysis: AIExtractionResponse


class NotificationPayloadResponse(BaseModel):
    message_id: int
    mailbox_address: str | None = None
    sender_brand: str | None = None
    otp_code: str | None = None
    summary: str
    open_path: str


class MessageAnalyzeResponse(BaseModel):
    message_id: int
    analysis: AIExtractionResponse
    notification: NotificationPayloadResponse | None = None


class IngestMessageRequest(BaseModel):
    to_address: str
    from_address: str | None = None
    subject: str | None = None
    provider_message_id: str | None = None
    internet_message_id: str | None = None
    source_provider: str = "ingest"
    received_at: datetime | None = None
    body_text: str | None = None
    body_html: str | None = None
    raw_payload: dict[str, Any] | None = None
    has_attachments: bool = False


class IngestMessageResponse(BaseModel):
    mailbox_id: int
    mailbox_address: str
    message_id: int
    notification: NotificationPayloadResponse | None = None
