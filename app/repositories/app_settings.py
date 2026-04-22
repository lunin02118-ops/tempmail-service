from __future__ import annotations

from sqlalchemy import func, insert, select, update

from app.config import AppSettings
from app.db import app_settings_table, get_engine


class AppSettingsRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._engine = get_engine(settings.database_url)

    def get(self, key: str) -> str | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(app_settings_table.c.value)
                .where(app_settings_table.c.key == key)
                .limit(1)
            ).first()
            return None if row is None else str(row[0])

    def set(self, key: str, value: str) -> None:
        existing = self.get(key)
        with self._engine.begin() as conn:
            if existing is None:
                conn.execute(insert(app_settings_table).values(key=key, value=value))
            else:
                conn.execute(
                    update(app_settings_table)
                    .where(app_settings_table.c.key == key)
                    .values(value=value, updated_at=func.now())
                )
