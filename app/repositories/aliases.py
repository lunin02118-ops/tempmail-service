from __future__ import annotations

from sqlalchemy import insert, select

from app.config import AppSettings
from app.db import aliases_table, get_engine


class AliasRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)

    def create_alias(
        self,
        alias_local_part: str,
        alias_email: str,
        telegram_chat_id: str,
        description: str | None = None,
        telegram_user_id: str | None = None,
    ) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(aliases_table).values(
                    alias_local_part=alias_local_part,
                    alias_email=alias_email.lower(),
                    telegram_chat_id=telegram_chat_id,
                    telegram_user_id=telegram_user_id,
                    description=description,
                    is_active=1,
                )
            )
            return int(result.inserted_primary_key[0])

    def get_by_alias_email(self, alias_email: str) -> dict[str, object] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(aliases_table).where(aliases_table.c.alias_email == alias_email.lower()).limit(1)
            ).mappings().first()
            return None if row is None else dict(row)

    def list_aliases(self) -> list[dict[str, object]]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(aliases_table).order_by(aliases_table.c.id.asc())).mappings().all()
            return [dict(row) for row in rows]
