from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert, select, update

from app.config import AppSettings
from app.db import ai_extractions_table, get_engine


class AIExtractionRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)

    def get_by_message_id(self, message_id: int) -> dict[str, object] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(ai_extractions_table)
                .where(ai_extractions_table.c.message_id == message_id)
                .limit(1)
            ).mappings().first()
            return None if row is None else dict(row)

    def upsert(self, message_id: int, payload: dict[str, object | None]) -> dict[str, object]:
        existing = self.get_by_message_id(message_id)
        values = dict(payload)
        values["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        if existing is None:
            values["message_id"] = message_id
            values.setdefault("created_at", datetime.now(UTC).replace(tzinfo=None))
            with self._engine.begin() as conn:
                result = conn.execute(insert(ai_extractions_table).values(**values))
                extraction_id = int(result.inserted_primary_key[0])
            stored = self.get_by_message_id(message_id)
            if stored is None:
                raise RuntimeError(f"ai extraction {extraction_id} could not be loaded after insert")
            return stored

        with self._engine.begin() as conn:
            conn.execute(
                update(ai_extractions_table)
                .where(ai_extractions_table.c.message_id == message_id)
                .values(**values)
            )

        stored = self.get_by_message_id(message_id)
        if stored is None:
            raise RuntimeError("ai extraction could not be loaded after update")
        return stored
