from __future__ import annotations

from sqlalchemy import insert, select, update

from app.config import AppSettings
from app.db import get_engine, inbound_messages_table


class InboundMessageRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)

    def get_by_gmail_message_id(self, gmail_message_id: str) -> dict[str, object] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(inbound_messages_table)
                .where(inbound_messages_table.c.gmail_message_id == gmail_message_id)
                .limit(1)
            ).mappings().first()
            return None if row is None else dict(row)

    def update_parse_status(self, message_id: int, parse_status: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(inbound_messages_table)
                .where(inbound_messages_table.c.id == message_id)
                .values(parse_status=parse_status)
            )

    def create_message(self, payload: dict[str, str | None]) -> int:
        existing = self.get_by_gmail_message_id(str(payload["gmail_message_id"]))
        if existing is not None:
            return int(existing["id"])

        with self._engine.begin() as conn:
            result = conn.execute(
                insert(inbound_messages_table).values(
                    gmail_message_id=payload.get("gmail_message_id"),
                    internet_message_id=payload.get("internet_message_id"),
                    thread_id=payload.get("thread_id"),
                    alias_email=payload.get("alias_email"),
                    delivered_to=payload.get("delivered_to"),
                    from_address=payload.get("from_address"),
                    subject=payload.get("subject"),
                    received_at=payload.get("received_at"),
                    body_text=payload.get("body_text"),
                    body_html=payload.get("body_html"),
                    raw_headers_json=payload.get("raw_headers_json"),
                    parse_status=payload.get("parse_status"),
                )
            )
            return int(result.inserted_primary_key[0])
