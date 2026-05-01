from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Query, Response, status

from app.config import AppSettings
from app.repositories.ai_extractions import AIExtractionRepository
from app.repositories.mailboxes import MailboxRepository
from app.repositories.messages import MessageRepository
from app.schemas.tempmail import (
    AIExtractionResponse,
    IngestMessageRequest,
    IngestMessageResponse,
    MailboxCreateRequest,
    MailboxCreateResponse,
    MailboxResponse,
    MessageAnalyzeResponse,
    MessageDetailResponse,
    MessageSummaryResponse,
    NotificationPayloadResponse,
)
from app.services.ai_service import MessageAnalysisService
from app.services.mailbox_service import MailboxService
from app.services.session_service import SESSION_COOKIE_NAME, generate_session_token, hash_session_token
from app.services.text_encoding import normalize_email_content, repair_mojibake


router = APIRouter(tags=["tempmail"])
logger = logging.getLogger(__name__)


def get_settings() -> AppSettings:
    return AppSettings.from_env()


def get_mailbox_repository(settings: AppSettings = Depends(get_settings)) -> MailboxRepository:
    return MailboxRepository(settings)


def get_message_repository(settings: AppSettings = Depends(get_settings)) -> MessageRepository:
    return MessageRepository(settings)


def get_ai_extraction_repository(settings: AppSettings = Depends(get_settings)) -> AIExtractionRepository:
    return AIExtractionRepository(settings)


def get_mailbox_service(
    settings: AppSettings = Depends(get_settings),
    repo: MailboxRepository = Depends(get_mailbox_repository),
) -> MailboxService:
    return MailboxService(settings, repo)


def get_analysis_service(settings: AppSettings = Depends(get_settings)) -> MessageAnalysisService:
    return MessageAnalysisService(settings)


def _parse_action_links(raw_value: object) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value]
    if isinstance(raw_value, str):
        try:
            loaded = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, list):
            return [str(item) for item in loaded]
    return []


def _serialize_mailbox(mailbox: dict[str, object]) -> MailboxResponse:
    return MailboxResponse(
        id=int(mailbox["id"]),
        local_part=str(mailbox["local_part"]),
        domain=str(mailbox["domain"]),
        address=str(mailbox["address"]),
        visibility=str(mailbox["visibility"]),
        description=str(mailbox["description"]) if mailbox.get("description") is not None else None,
        is_active=bool(mailbox["is_active"]),
        created_at=mailbox["created_at"],
        last_seen_at=mailbox.get("last_seen_at"),
        expires_at=mailbox["expires_at"],
    )


def _clean_optional_text(value: object) -> str | None:
    return repair_mojibake(str(value)) if value is not None else None


def _serialize_message_summary(message: dict[str, object]) -> MessageSummaryResponse:
    return MessageSummaryResponse(
        id=int(message["id"]),
        mailbox_id=int(message["mailbox_id"]),
        mailbox_address=str(message["mailbox_address"]),
        mailbox_local_part=str(message["mailbox_local_part"]) if message.get("mailbox_local_part") is not None else None,
        mailbox_domain=str(message["mailbox_domain"]) if message.get("mailbox_domain") is not None else None,
        from_address=_clean_optional_text(message.get("from_address")),
        to_address=_clean_optional_text(message.get("to_address")),
        subject=_clean_optional_text(message.get("subject")),
        received_at=message["received_at"],
        has_attachments=bool(message["has_attachments"]),
        is_unread=bool(message["is_unread"]),
        ai_summary=_clean_optional_text(message.get("ai_summary")),
        otp_code=str(message["otp_code"]) if message.get("otp_code") is not None else None,
        action_required=_clean_optional_text(message.get("action_required")),
        sender_brand=_clean_optional_text(message.get("sender_brand")),
        ai_status=str(message["ai_status"]) if message.get("ai_status") is not None else None,
    )


def _serialize_analysis(message: dict[str, object]) -> AIExtractionResponse:
    return AIExtractionResponse(
        provider=str(message["ai_provider"]) if message.get("ai_provider") is not None else None,
        model=str(message["ai_model"]) if message.get("ai_model") is not None else None,
        status=str(message["ai_status"]) if message.get("ai_status") is not None else None,
        summary=str(message["ai_summary"]) if message.get("ai_summary") is not None else None,
        message_type=str(message["message_type"]) if message.get("message_type") is not None else None,
        otp_code=str(message["otp_code"]) if message.get("otp_code") is not None else None,
        action_required=str(message["action_required"]) if message.get("action_required") is not None else None,
        action_links=_parse_action_links(message.get("action_links_json")),
        sender_brand=str(message["sender_brand"]) if message.get("sender_brand") is not None else None,
        confidence=str(message["ai_confidence"]) if message.get("ai_confidence") is not None else None,
        error_text=str(message["ai_error_text"]) if message.get("ai_error_text") is not None else None,
    )


def _serialize_message_detail(message: dict[str, object]) -> MessageDetailResponse:
    return MessageDetailResponse(
        **_serialize_message_summary(message).model_dump(),
        source_provider=str(message["source_provider"]),
        provider_message_id=_clean_optional_text(message.get("provider_message_id")),
        internet_message_id=_clean_optional_text(message.get("internet_message_id")),
        body_text=normalize_email_content(_clean_optional_text(message.get("body_text"))),
        body_html=normalize_email_content(_clean_optional_text(message.get("body_html"))),
        raw_payload_json=str(message["raw_payload_json"]) if message.get("raw_payload_json") is not None else None,
        analysis=_serialize_analysis(message),
    )


def _serialize_notification(notification: dict[str, object] | None) -> NotificationPayloadResponse | None:
    if notification is None:
        return None
    return NotificationPayloadResponse(
        message_id=int(notification["message_id"]),
        mailbox_address=str(notification["mailbox_address"]) if notification.get("mailbox_address") is not None else None,
        sender_brand=str(notification["sender_brand"]) if notification.get("sender_brand") is not None else None,
        otp_code=str(notification["otp_code"]) if notification.get("otp_code") is not None else None,
        summary=str(notification["summary"]),
        open_path=str(notification["open_path"]),
    )


def get_optional_session_token(
    x_session_token: str | None = Header(default=None),
    tm_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> str | None:
    return x_session_token or tm_session


def require_session_token(session_token: str | None = Depends(get_optional_session_token)) -> str:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing session token")
    return session_token


def get_session_token_hash(
    settings: AppSettings = Depends(get_settings),
    session_token: str = Depends(require_session_token),
) -> str:
    return hash_session_token(session_token, settings.session_secret)


def require_ingest_secret(
    settings: AppSettings = Depends(get_settings),
    x_ingest_webhook_secret: str | None = Header(default=None),
) -> None:
    expected_secret = settings.ingest_webhook_secret
    if not expected_secret:
        return
    if x_ingest_webhook_secret != expected_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid ingest secret")


async def _verify_turnstile(turnstile_token: str | None, settings: AppSettings) -> None:
    if not settings.turnstile_enabled or not settings.turnstile_secret_key:
        return
    if not turnstile_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="turnstile token is required")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": settings.turnstile_secret_key,
                "response": turnstile_token,
            },
        )

    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="turnstile verification failed")


def _is_completed_groq_analysis(extraction: dict[str, object] | None) -> bool:
    if extraction is None:
        return False
    return str(extraction.get("provider") or "") == "groq" and str(extraction.get("status") or "") == "completed"


async def _run_auto_analysis_for_message(
    *,
    message_id: int,
    session_token_hash: str,
    settings: AppSettings,
) -> None:
    if not settings.groq_api_keys:
        return

    message_repo = MessageRepository(settings)
    ai_repo = AIExtractionRepository(settings)
    analysis_service = MessageAnalysisService(settings)

    existing_extraction = ai_repo.get_by_message_id(message_id)
    if _is_completed_groq_analysis(existing_extraction):
        return

    message = message_repo.get_for_session(message_id, session_token_hash, mark_as_read=False)
    if message is None:
        return

    try:
        analysis_payload = await analysis_service.analyze_message(message, allow_remote=True)
        ai_repo.upsert(message_id, analysis_payload)
    except Exception:
        logger.exception("auto-analysis failed for message_id=%s", message_id)


@router.post("/mailboxes", response_model=MailboxCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_mailbox(
    request: MailboxCreateRequest,
    response: Response,
    settings: AppSettings = Depends(get_settings),
    provided_session_token: str | None = Depends(get_optional_session_token),
    mailbox_service: MailboxService = Depends(get_mailbox_service),
) -> MailboxCreateResponse:
    await _verify_turnstile(request.turnstile_token, settings)

    session_token = provided_session_token or generate_session_token()
    session_token_hash = hash_session_token(session_token, settings.session_secret)

    try:
        mailbox = mailbox_service.create_mailbox(
            session_token_hash=session_token_hash,
            description=request.description,
            expires_in_minutes=request.expires_in_minutes,
            requested_local_part=request.requested_local_part,
            requested_domain=request.requested_domain,
            local_part_length=request.local_part_length,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )
    return MailboxCreateResponse(session_token=session_token, mailbox=_serialize_mailbox(mailbox))


@router.get("/mailboxes", response_model=list[MailboxResponse])
def list_mailboxes(
    session_token_hash: str = Depends(get_session_token_hash),
    repo: MailboxRepository = Depends(get_mailbox_repository),
) -> list[MailboxResponse]:
    return [_serialize_mailbox(mailbox) for mailbox in repo.list_for_session(session_token_hash)]


@router.get("/inbox", response_model=list[MessageSummaryResponse])
def list_unified_inbox(
    session_token_hash: str = Depends(get_session_token_hash),
    repo: MessageRepository = Depends(get_message_repository),
) -> list[MessageSummaryResponse]:
    return [_serialize_message_summary(message) for message in repo.list_for_session(session_token_hash)]


@router.get("/mailboxes/{mailbox_id}/messages", response_model=list[MessageSummaryResponse])
def list_mailbox_messages(
    mailbox_id: int,
    session_token_hash: str = Depends(get_session_token_hash),
    mailbox_repo: MailboxRepository = Depends(get_mailbox_repository),
    message_repo: MessageRepository = Depends(get_message_repository),
) -> list[MessageSummaryResponse]:
    mailbox = mailbox_repo.get_by_id_for_session(mailbox_id, session_token_hash)
    if mailbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mailbox not found")
    return [_serialize_message_summary(message) for message in message_repo.list_for_mailbox(mailbox_id, session_token_hash)]


@router.get("/messages/{message_id}", response_model=MessageDetailResponse)
def get_message_detail(
    message_id: int,
    session_token_hash: str = Depends(get_session_token_hash),
    repo: MessageRepository = Depends(get_message_repository),
) -> MessageDetailResponse:
    message = repo.get_for_session(message_id, session_token_hash, mark_as_read=True)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    return _serialize_message_detail(message)


@router.post("/messages/{message_id}/analyze", response_model=MessageAnalyzeResponse)
async def analyze_message(
    message_id: int,
    session_token_hash: str = Depends(get_session_token_hash),
    message_repo: MessageRepository = Depends(get_message_repository),
    ai_repo: AIExtractionRepository = Depends(get_ai_extraction_repository),
    analysis_service: MessageAnalysisService = Depends(get_analysis_service),
) -> MessageAnalyzeResponse:
    message = message_repo.get_for_session(message_id, session_token_hash, mark_as_read=False)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    analysis_payload = await analysis_service.analyze_message(message, allow_remote=True)
    stored = ai_repo.upsert(message_id, analysis_payload)
    notification = message_repo.build_notification_payload(message_id, session_token_hash)

    combined = dict(message)
    combined.update(
        {
            "ai_provider": stored.get("provider"),
            "ai_model": stored.get("model"),
            "ai_status": stored.get("status"),
            "ai_summary": stored.get("summary"),
            "message_type": stored.get("message_type"),
            "otp_code": stored.get("otp_code"),
            "action_required": stored.get("action_required"),
            "action_links_json": stored.get("action_links_json"),
            "sender_brand": stored.get("sender_brand"),
            "ai_confidence": stored.get("confidence"),
            "ai_error_text": stored.get("error_text"),
        }
    )

    return MessageAnalyzeResponse(
        message_id=message_id,
        analysis=_serialize_analysis(combined),
        notification=_serialize_notification(notification),
    )


@router.get("/notifications/latest", response_model=NotificationPayloadResponse | None)
def get_latest_notification(
    session_token_hash: str = Depends(get_session_token_hash),
    repo: MessageRepository = Depends(get_message_repository),
) -> NotificationPayloadResponse | None:
    notification = repo.build_latest_code_notification_payload(session_token_hash)
    return _serialize_notification(notification)


@router.get("/widget/mailboxes", response_model=list[MailboxResponse])
def list_widget_mailboxes(
    repo: MailboxRepository = Depends(get_mailbox_repository),
    limit: int = Query(default=250, ge=1, le=1000),
) -> list[MailboxResponse]:
    return [_serialize_mailbox(mailbox) for mailbox in repo.list_all_active(limit=limit)]


@router.get("/widget/notifications/latest", response_model=NotificationPayloadResponse | None)
def get_widget_latest_notification(
    repo: MessageRepository = Depends(get_message_repository),
) -> NotificationPayloadResponse | None:
    notification = repo.build_latest_code_notification_payload_for_all()
    return _serialize_notification(notification)


@router.post("/ingest/messages", response_model=IngestMessageResponse)
async def ingest_message(
    request: IngestMessageRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_ingest_secret),
    settings: AppSettings = Depends(get_settings),
    mailbox_repo: MailboxRepository = Depends(get_mailbox_repository),
    message_repo: MessageRepository = Depends(get_message_repository),
    ai_repo: AIExtractionRepository = Depends(get_ai_extraction_repository),
    analysis_service: MessageAnalysisService = Depends(get_analysis_service),
) -> IngestMessageResponse:
    mailbox = mailbox_repo.get_by_address(request.to_address)
    if mailbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mailbox not found")

    message_id = message_repo.create_ingested_message(
        mailbox_id=int(mailbox["id"]),
        source_provider=request.source_provider,
        provider_message_id=request.provider_message_id,
        internet_message_id=request.internet_message_id,
        from_address=repair_mojibake(request.from_address),
        to_address=request.to_address,
        subject=repair_mojibake(request.subject),
        received_at=request.received_at,
        body_text=normalize_email_content(request.body_text),
        body_html=normalize_email_content(request.body_html),
        raw_payload_json=json.dumps(request.raw_payload) if request.raw_payload is not None else None,
        has_attachments=request.has_attachments,
    )
    mailbox_repo.touch_last_seen(int(mailbox["id"]))

    session_token_hash = str(mailbox["session_token_hash"])
    message = message_repo.get_for_session(message_id, session_token_hash, mark_as_read=False)
    existing_extraction = ai_repo.get_by_message_id(message_id)
    if message is not None:
        if existing_extraction is None:
            deterministic_payload = await analysis_service.analyze_message(message, allow_remote=False)
            existing_extraction = ai_repo.upsert(message_id, deterministic_payload)

        if settings.groq_api_keys and not _is_completed_groq_analysis(existing_extraction):
            background_tasks.add_task(
                _run_auto_analysis_for_message,
                message_id=message_id,
                session_token_hash=session_token_hash,
                settings=settings,
            )

    notification = message_repo.build_notification_payload(message_id, session_token_hash)
    return IngestMessageResponse(
        mailbox_id=int(mailbox["id"]),
        mailbox_address=str(mailbox["address"]),
        message_id=message_id,
        notification=_serialize_notification(notification),
    )
