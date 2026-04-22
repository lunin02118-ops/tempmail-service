from __future__ import annotations

from pydantic import BaseModel, Field


class AliasCreateRequest(BaseModel):
    telegram_chat_id: str = Field(..., min_length=1)
    description: str | None = None
    telegram_user_id: str | None = None
    local_part_length: int = Field(8, ge=4, le=32)


class AliasResponse(BaseModel):
    id: int
    alias_local_part: str
    alias_email: str
    telegram_chat_id: str
    telegram_user_id: str | None = None
    description: str | None = None
    is_active: bool
