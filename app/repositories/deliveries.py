from __future__ import annotations

from sqlalchemy import insert

from app.config import AppSettings
from app.db import deliveries_table, get_engine


class DeliveryRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)

    def create_delivery(
        self,
        inbound_message_id: int,
        telegram_chat_id: str,
        status: str,
        telegram_message_id: str | None = None,
        error_text: str | None = None,
    ) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(deliveries_table).values(
                    inbound_message_id=inbound_message_id,
                    telegram_chat_id=telegram_chat_id,
                    telegram_message_id=telegram_message_id,
                    status=status,
                    error_text=error_text,
                )
            )
            return int(result.inserted_primary_key[0])
