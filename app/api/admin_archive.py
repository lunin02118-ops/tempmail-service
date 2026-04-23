from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.api.tempmail import _serialize_analysis, _serialize_message_summary, get_message_repository
from app.repositories.messages import MessageRepository
from app.schemas.tempmail import MessageDetailResponse, MessageSummaryResponse


router = APIRouter(tags=["admin-archive"])


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def require_archive_admin(
    authorization: str | None = Header(default=None),
    x_archive_admin_token: str | None = Header(default=None),
) -> None:
    expected_token = os.getenv("ARCHIVE_ADMIN_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="archive is not configured")

    provided_token = (x_archive_admin_token or _bearer_token(authorization) or "").strip()
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid archive token")


@router.get("/admin/archive/messages", response_model=list[MessageSummaryResponse])
def list_admin_archive_messages(
    _: None = Depends(require_archive_admin),
    repo: MessageRepository = Depends(get_message_repository),
    limit: int = Query(default=250, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
) -> list[MessageSummaryResponse]:
    return [
        _serialize_message_summary(message)
        for message in repo.list_all_for_admin(limit=limit, offset=offset, search=q)
    ]


@router.get("/admin/archive/messages/{message_id}", response_model=MessageDetailResponse)
def get_admin_archive_message(
    message_id: int,
    _: None = Depends(require_archive_admin),
    repo: MessageRepository = Depends(get_message_repository),
) -> MessageDetailResponse:
    message = repo.get_for_admin(message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    return MessageDetailResponse(
        **_serialize_message_summary(message).model_dump(),
        source_provider=str(message["source_provider"]),
        provider_message_id=str(message["provider_message_id"]) if message.get("provider_message_id") is not None else None,
        internet_message_id=str(message["internet_message_id"]) if message.get("internet_message_id") is not None else None,
        body_text=str(message["body_text"]) if message.get("body_text") is not None else None,
        body_html=str(message["body_html"]) if message.get("body_html") is not None else None,
        raw_payload_json=str(message["raw_payload_json"]) if message.get("raw_payload_json") is not None else None,
        analysis=_serialize_analysis(message),
    )
