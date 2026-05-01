from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, update

from app.config import AppSettings
from app.db import get_engine, mailboxes_table


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
