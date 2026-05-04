from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, update

from app.config import AppSettings
from app.db import get_engine, mailboxes_table


SERVICE_MAILBOX_VISIBILITY = "public"
SERVICE_MAILBOX_TTL_DAYS = 365 * 10


def derive_service_session_token_hash(session_secret: str, address: str) -> str:
    digest = hashlib.sha256()
    digest.update(session_secret.encode("utf-8"))
    digest.update(b":service:gmail:")
    digest.update(address.lower().encode("utf-8"))
    return digest.hexdigest()


class MailboxRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)
        self._settings = settings

    def create_mailbox(
        self,
        *,
        local_part: str,
        domain: str,
        address: str,
        session_token_hash: str,
        description: str | None = None,
        expires_in_minutes: int | None = None,
        visibility: str = "session",
    ) -> dict[str, object]:
        ttl_minutes = expires_in_minutes or self._settings.mailbox_default_ttl_minutes
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=ttl_minutes)
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(mailboxes_table).values(
                    local_part=local_part,
                    domain=domain,
                    address=address.lower(),
                    visibility=visibility,
                    session_token_hash=session_token_hash,
                    description=description,
                    is_active=1,
                    expires_at=expires_at,
                    last_seen_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            mailbox_id = int(result.inserted_primary_key[0])
        mailbox = self.get_by_id_for_session(mailbox_id, session_token_hash)
        if mailbox is None:
            raise RuntimeError("mailbox was created but could not be loaded")
        return mailbox

    def list_for_session(self, session_token_hash: str) -> list[dict[str, object]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(mailboxes_table)
                .where(mailboxes_table.c.session_token_hash == session_token_hash)
                .where(mailboxes_table.c.is_active == 1)
                .order_by(mailboxes_table.c.created_at.desc(), mailboxes_table.c.id.desc())
            ).mappings().all()
            return [dict(row) for row in rows]

    def list_all_active(self, *, limit: int = 250) -> list[dict[str, object]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(mailboxes_table)
                .where(mailboxes_table.c.is_active == 1)
                .order_by(mailboxes_table.c.created_at.desc(), mailboxes_table.c.id.desc())
                .limit(limit)
            ).mappings().all()
            return [dict(row) for row in rows]

    def get_by_address(self, address: str) -> dict[str, object] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(mailboxes_table)
                .where(mailboxes_table.c.address == address.lower())
                .where(mailboxes_table.c.is_active == 1)
                .limit(1)
            ).mappings().first()
            return None if row is None else dict(row)

    def get_by_id_for_session(self, mailbox_id: int, session_token_hash: str) -> dict[str, object] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(mailboxes_table)
                .where(mailboxes_table.c.id == mailbox_id)
                .where(mailboxes_table.c.session_token_hash == session_token_hash)
                .where(mailboxes_table.c.is_active == 1)
                .limit(1)
            ).mappings().first()
            return None if row is None else dict(row)

    def touch_last_seen(self, mailbox_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(mailboxes_table)
                .where(mailboxes_table.c.id == mailbox_id)
                .values(last_seen_at=datetime.now(UTC).replace(tzinfo=None))
            )

    def list_public(self, *, limit: int = 250) -> list[dict[str, object]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(mailboxes_table)
                .where(mailboxes_table.c.is_active == 1)
                .where(mailboxes_table.c.visibility == SERVICE_MAILBOX_VISIBILITY)
                .order_by(mailboxes_table.c.created_at.desc(), mailboxes_table.c.id.desc())
                .limit(limit)
            ).mappings().all()
            return [dict(row) for row in rows]

    def get_or_create_service_mailbox(
        self,
        *,
        address: str,
        description: str | None = None,
    ) -> dict[str, object]:
        normalized = address.strip().lower()
        if not normalized or "@" not in normalized:
            raise ValueError("service mailbox address must be a valid email")

        existing = self.get_by_address(normalized)
        if existing is not None:
            return existing

        local_part, domain = normalized.split("@", 1)
        session_token_hash = derive_service_session_token_hash(self._settings.session_secret, normalized)
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=SERVICE_MAILBOX_TTL_DAYS)
        with self._engine.begin() as conn:
            conn.execute(
                insert(mailboxes_table).values(
                    local_part=local_part,
                    domain=domain,
                    address=normalized,
                    visibility=SERVICE_MAILBOX_VISIBILITY,
                    session_token_hash=session_token_hash,
                    description=description,
                    is_active=1,
                    expires_at=expires_at,
                    last_seen_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        created = self.get_by_address(normalized)
        if created is None:
            raise RuntimeError("service mailbox was not created")
        return created
