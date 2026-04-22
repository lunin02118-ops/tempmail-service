from __future__ import annotations

from app.repositories.aliases import AliasRepository


def resolve_chat_id_for_alias(repo: AliasRepository, alias_email: str) -> str | None:
    row = repo.get_by_alias_email(alias_email.lower())
    if row is None:
        return None
    if int(row["is_active"]) != 1:
        return None
    return str(row["telegram_chat_id"])
