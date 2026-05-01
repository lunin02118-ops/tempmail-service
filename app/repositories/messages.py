from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, insert, join, or_, outerjoin, select, update

from app.config import AppSettings
from app.db import ai_extractions_table, get_engine, mailboxes_table, messages_table


class MessageRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)

    def _message_summary_columns(self) -> tuple:
        return (
            messages_table.c.id,
            messages_table.c.mailbox_id,
            messages_table.c.from_address,
            messages_table.c.to_address,
            messages_table.c.subject,
            messages_table.c.received_at,
            messages_table.c.has_attachments,
            messages_table.c.is_unread,
        )

    def _normalize_received_at(self, received_at: datetime | None) -> datetime:
        if received_at is None:
            return datetime.now(UTC).replace(tzinfo=None)
        if received_at.tzinfo is not None:
            return received_at.astimezone(UTC).replace(tzinfo=None)
        return received_at

    def _get_existing_message_id(self, source_provider: str, provider_message_id: str | None) -> int | None:
        if not provider_message_id:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(
                select(messages_table.c.id)
                .where(messages_table.c.source_provider == source_provider)
                .where(messages_table.c.provider_message_id == provider_message_id)
                .limit(1)
            ).first()
            return None if row is None else int(row[0])

    def create_ingested_message(
        self,
        *,
        mailbox_id: int,
        source_provider: str,
        provider_message_id: str | None,
        internet_message_id: str | None,
        from_address: str | None,
        to_address: str | None,
        subject: str | None,
        received_at: datetime | None,
        body_text: str | None,
        body_html: str | None,
        raw_payload_json: str | None,
        has_attachments: bool = False,
    ) -> int:
        existing_message_id = self._get_existing_message_id(source_provider, provider_message_id)
        if existing_message_id is not None:
            return existing_message_id

        with self._engine.begin() as conn:
            result = conn.execute(
                insert(messages_table).values(
                    mailbox_id=mailbox_id,
                    source_provider=source_provider,
                    provider_message_id=provider_message_id,
                    internet_message_id=internet_message_id,
                    from_address=from_address,
                    to_address=to_address,
                    subject=subject,
                    received_at=self._normalize_received_at(received_at),
                    body_text=body_text,
                    body_html=body_html,
                    raw_payload_json=raw_payload_json,
                    has_attachments=1 if has_attachments else 0,
                    is_unread=1,
                )
            )
            return int(result.inserted_primary_key[0])

    def list_for_session(self, session_token_hash: str) -> list[dict[str, object]]:
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)

        query = (
            select(
                *self._message_summary_columns(),
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.status.label("ai_status"),
            )
            .select_from(extraction_join)
            .where(mailboxes_table.c.session_token_hash == session_token_hash)
            .where(mailboxes_table.c.is_active == 1)
            .order_by(messages_table.c.received_at.desc(), messages_table.c.id.desc())
        )

        with self._engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
            return [dict(row) for row in rows]

    def get_latest_code_for_session(self, session_token_hash: str) -> dict[str, object] | None:
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)

        query = (
            select(
                *self._message_summary_columns(),
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.status.label("ai_status"),
            )
            .select_from(extraction_join)
            .where(mailboxes_table.c.session_token_hash == session_token_hash)
            .where(mailboxes_table.c.is_active == 1)
            .where(ai_extractions_table.c.otp_code.is_not(None))
            .where(ai_extractions_table.c.otp_code != "")
            .order_by(messages_table.c.created_at.desc(), messages_table.c.id.desc())
            .limit(1)
        )

        with self._engine.connect() as conn:
            row = conn.execute(query).mappings().first()
            return None if row is None else dict(row)

    def get_latest_code_for_all(self) -> dict[str, object] | None:
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)

        query = (
            select(
                *self._message_summary_columns(),
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.status.label("ai_status"),
            )
            .select_from(extraction_join)
            .where(mailboxes_table.c.is_active == 1)
            .where(ai_extractions_table.c.otp_code.is_not(None))
            .where(ai_extractions_table.c.otp_code != "")
            .order_by(messages_table.c.created_at.desc(), messages_table.c.id.desc())
            .limit(1)
        )

        with self._engine.connect() as conn:
            row = conn.execute(query).mappings().first()
            return None if row is None else dict(row)

    def list_for_mailbox(self, mailbox_id: int, session_token_hash: str) -> list[dict[str, object]]:
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)
        query = (
            select(
                *self._message_summary_columns(),
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.status.label("ai_status"),
            )
            .select_from(extraction_join)
            .where(messages_table.c.mailbox_id == mailbox_id)
            .where(mailboxes_table.c.session_token_hash == session_token_hash)
            .where(mailboxes_table.c.is_active == 1)
            .order_by(messages_table.c.received_at.desc(), messages_table.c.id.desc())
        )
        with self._engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
            return [dict(row) for row in rows]

    def list_all_for_admin(self, *, limit: int = 250, offset: int = 0, search: str | None = None) -> list[dict[str, object]]:
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)
        query = (
            select(
                *self._message_summary_columns(),
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.status.label("ai_status"),
            )
            .select_from(extraction_join)
            .order_by(messages_table.c.received_at.desc(), messages_table.c.id.desc())
            .limit(limit)
            .offset(offset)
        )

        if search:
            needle = f"%{search.strip()}%"
            query = query.where(
                or_(
                    messages_table.c.subject.ilike(needle),
                    messages_table.c.from_address.ilike(needle),
                    messages_table.c.to_address.ilike(needle),
                    mailboxes_table.c.address.ilike(needle),
                    ai_extractions_table.c.otp_code.ilike(needle),
                    ai_extractions_table.c.sender_brand.ilike(needle),
                )
            )

        with self._engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
            return [dict(row) for row in rows]

    def _build_message_detail_query(self, message_id: int, session_token_hash: str):
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)
        return (
            select(
                messages_table,
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.provider.label("ai_provider"),
                ai_extractions_table.c.model.label("ai_model"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.message_type.label("message_type"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.action_links_json.label("action_links_json"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.confidence.label("ai_confidence"),
                ai_extractions_table.c.status.label("ai_status"),
                ai_extractions_table.c.error_text.label("ai_error_text"),
            )
            .select_from(extraction_join)
            .where(messages_table.c.id == message_id)
            .where(mailboxes_table.c.session_token_hash == session_token_hash)
            .where(mailboxes_table.c.is_active == 1)
            .limit(1)
        )

    def get_for_session(
        self,
        message_id: int,
        session_token_hash: str,
        *,
        mark_as_read: bool = True,
    ) -> dict[str, object] | None:
        query = self._build_message_detail_query(message_id, session_token_hash)
        with self._engine.begin() as conn:
            row = conn.execute(query).mappings().first()
            if row is None:
                return None
            if mark_as_read:
                conn.execute(
                    update(messages_table)
                    .where(messages_table.c.id == message_id)
                    .values(is_unread=0)
                )
            return dict(row)

    def get_for_admin(self, message_id: int) -> dict[str, object] | None:
        mailbox_join = join(messages_table, mailboxes_table, messages_table.c.mailbox_id == mailboxes_table.c.id)
        extraction_join = outerjoin(mailbox_join, ai_extractions_table, ai_extractions_table.c.message_id == messages_table.c.id)
        query = (
            select(
                messages_table,
                mailboxes_table.c.address.label("mailbox_address"),
                mailboxes_table.c.local_part.label("mailbox_local_part"),
                mailboxes_table.c.domain.label("mailbox_domain"),
                ai_extractions_table.c.provider.label("ai_provider"),
                ai_extractions_table.c.model.label("ai_model"),
                ai_extractions_table.c.summary.label("ai_summary"),
                ai_extractions_table.c.message_type.label("message_type"),
                ai_extractions_table.c.otp_code.label("otp_code"),
                ai_extractions_table.c.action_required.label("action_required"),
                ai_extractions_table.c.action_links_json.label("action_links_json"),
                ai_extractions_table.c.sender_brand.label("sender_brand"),
                ai_extractions_table.c.confidence.label("ai_confidence"),
                ai_extractions_table.c.status.label("ai_status"),
                ai_extractions_table.c.error_text.label("ai_error_text"),
            )
            .select_from(extraction_join)
            .where(messages_table.c.id == message_id)
            .limit(1)
        )
        with self._engine.connect() as conn:
            row = conn.execute(query).mappings().first()
            return None if row is None else dict(row)

    def _build_notification_from_message(self, message: dict[str, object] | None) -> dict[str, object] | None:
        if message is None:
            return None

        summary = str(message.get("ai_summary") or message.get("subject") or "(no subject)")
        return {
            "message_id": int(message["id"]),
            "mailbox_address": message.get("mailbox_address"),
            "sender_brand": message.get("sender_brand") or message.get("from_address"),
            "otp_code": message.get("otp_code"),
            "summary": summary,
            "open_path": f"/messages/{int(message['id'])}",
        }

    def build_notification_payload(self, message_id: int, session_token_hash: str) -> dict[str, object] | None:
        message = self.get_for_session(message_id, session_token_hash, mark_as_read=False)
        return self._build_notification_from_message(message)

    def build_latest_code_notification_payload(self, session_token_hash: str) -> dict[str, object] | None:
        message = self.get_latest_code_for_session(session_token_hash)
        return self._build_notification_from_message(message)

    def build_latest_code_notification_payload_for_all(self) -> dict[str, object] | None:
        message = self.get_latest_code_for_all()
        return self._build_notification_from_message(message)
