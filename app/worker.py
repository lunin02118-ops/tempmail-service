from __future__ import annotations

import asyncio
import sys
import time
import traceback

from app.config import AppSettings
from app.db import initialize_database
from app.repositories.ai_extractions import AIExtractionRepository
from app.repositories.aliases import AliasRepository
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.repositories.mailboxes import MailboxRepository
from app.repositories.messages import MessageRepository
from app.services.ai_service import MessageAnalysisService
from app.services.bot_service import handle_update
from app.services.gmail_client import GmailClient
from app.services.gmail_tempmail_service import ingest_gmail_message_to_tempmail
from app.services.ingestion_service import ingest_gmail_message
from app.services.telegram_client import TelegramClient

LAST_SEEN_GMAIL_MESSAGE_ID_KEY = "last_seen_gmail_message_id"
LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY = "last_seen_gmail_tempmail_message_id"
TELEGRAM_LAST_UPDATE_ID_KEY = "telegram_last_update_id"
GMAIL_PAGE_SIZE = 100
GMAIL_TEMPMAIL_MAX_PER_RUN = 25


def _collect_pending_message_ids(
    gmail_client: GmailClient,
    settings_repo: AppSettingsRepository,
    cursor_key: str = LAST_SEEN_GMAIL_MESSAGE_ID_KEY,
) -> tuple[list[str], int, str | None]:
    last_seen = settings_repo.get(cursor_key)
    pending_ids: list[str] = []
    skipped_seen = 0
    newest_seen_message_id: str | None = None
    page_token: str | None = None

    while True:
        cursor = gmail_client.list_message_ids(max_results=GMAIL_PAGE_SIZE, page_token=page_token)
        message_ids = list(cursor.get("message_ids", []))
        if newest_seen_message_id is None and message_ids:
            newest_seen_message_id = message_ids[0]
        if not message_ids:
            break

        boundary_found = False
        for message_id in message_ids:
            if last_seen and message_id == last_seen:
                skipped_seen += 1
                boundary_found = True
                break
            pending_ids.append(message_id)

        if boundary_found:
            break

        next_page_token = cursor.get("next_page_token")
        if not isinstance(next_page_token, str) or not next_page_token:
            break
        page_token = next_page_token

    pending_ids.reverse()
    return pending_ids, skipped_seen, newest_seen_message_id or last_seen


def process_once(
    settings: AppSettings,
    gmail_client: GmailClient | None = None,
    telegram_client: TelegramClient | None = None,
) -> dict[str, int | str | None]:
    initialize_database(settings)

    owns_gmail_client = gmail_client is None
    gmail_client = gmail_client or GmailClient(settings)
    try:
        if telegram_client is None:
            if not settings.telegram_bot_token:
                raise ValueError("TELEGRAM_BOT_TOKEN is required for worker mode")
            telegram_client = TelegramClient(settings.telegram_bot_token)

        alias_repo = AliasRepository(settings)
        message_repo = InboundMessageRepository(settings)
        settings_repo = AppSettingsRepository(settings)

        pending_ids, skipped_seen, newest_seen_message_id = _collect_pending_message_ids(
            gmail_client,
            settings_repo,
            cursor_key=LAST_SEEN_GMAIL_MESSAGE_ID_KEY,
        )

        delivered = 0
        last_processed_message_id = settings_repo.get(LAST_SEEN_GMAIL_MESSAGE_ID_KEY)
        for message_id in pending_ids:
            gmail_message = gmail_client.get_message(message_id)
            result = ingest_gmail_message(
                settings=settings,
                gmail_message=gmail_message,
                alias_repo=alias_repo,
                message_repo=message_repo,
                telegram_client=telegram_client,
            )
            if result.get("status") == "delivered":
                delivered += 1
            settings_repo.set(LAST_SEEN_GMAIL_MESSAGE_ID_KEY, message_id)
            last_processed_message_id = message_id

        return {
            "processed": len(pending_ids),
            "delivered": delivered,
            "skipped_seen": skipped_seen,
            "last_seen_gmail_message_id": last_processed_message_id or newest_seen_message_id,
        }
    finally:
        if owns_gmail_client:
            gmail_client.close()


async def _ingest_pending_gmail_messages(
    *,
    settings: AppSettings,
    gmail_client: GmailClient,
    pending_ids: list[str],
    settings_repo: AppSettingsRepository,
    mailbox_repo: MailboxRepository,
    message_repo: MessageRepository,
    ai_repo: AIExtractionRepository,
    analysis_service: MessageAnalysisService,
    allow_remote_ai: bool,
) -> tuple[int, str | None]:
    delivered = 0
    last_processed: str | None = None
    for message_id in pending_ids:
        gmail_message = gmail_client.get_message(message_id)
        result = await ingest_gmail_message_to_tempmail(
            settings=settings,
            gmail_message=gmail_message,
            mailbox_repo=mailbox_repo,
            message_repo=message_repo,
            ai_repo=ai_repo,
            analysis_service=analysis_service,
            allow_remote_ai=allow_remote_ai,
        )
        if result.get("status") == "delivered":
            delivered += 1
        settings_repo.set(LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY, message_id)
        last_processed = message_id
    return delivered, last_processed


def process_gmail_tempmail_once(
    settings: AppSettings,
    gmail_client: GmailClient | None = None,
    *,
    max_messages: int = GMAIL_TEMPMAIL_MAX_PER_RUN,
    allow_remote_ai: bool = True,
) -> dict[str, int | str | bool | None]:
    initialize_database(settings)

    if not settings.gmail_tempmail_address:
        raise ValueError("GMAIL_TEMPMAIL_ADDRESS is required for tempmail Gmail ingest")
    if not settings.has_gmail_ingest:
        raise ValueError("GMAIL_CLIENT_SECRET_PATH and GMAIL_TOKEN_PATH are required for tempmail Gmail ingest")

    owns_gmail_client = gmail_client is None
    gmail_client = gmail_client or GmailClient(settings)
    try:
        settings_repo = AppSettingsRepository(settings)

        existing_cursor = settings_repo.get(LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY)
        if not existing_cursor:
            probe = gmail_client.list_message_ids(max_results=1)
            newest = (probe.get("message_ids") or [None])[0]
            if newest:
                settings_repo.set(LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY, str(newest))
                return {
                    "processed": 0,
                    "delivered": 0,
                    "skipped_seen": 0,
                    "last_seen_gmail_tempmail_message_id": str(newest),
                    "bootstrap": True,
                }
            return {
                "processed": 0,
                "delivered": 0,
                "skipped_seen": 0,
                "last_seen_gmail_tempmail_message_id": None,
                "bootstrap": True,
            }

        pending_ids, skipped_seen, newest_seen_message_id = _collect_pending_message_ids(
            gmail_client,
            settings_repo,
            cursor_key=LAST_SEEN_GMAIL_TEMPMAIL_MESSAGE_ID_KEY,
        )

        truncated = False
        if max_messages and len(pending_ids) > max_messages:
            pending_ids = pending_ids[-max_messages:]
            truncated = True

        if not pending_ids:
            return {
                "processed": 0,
                "delivered": 0,
                "skipped_seen": skipped_seen,
                "last_seen_gmail_tempmail_message_id": existing_cursor or newest_seen_message_id,
                "truncated": False,
                "bootstrap": False,
            }

        mailbox_repo = MailboxRepository(settings)
        message_repo = MessageRepository(settings)
        ai_repo = AIExtractionRepository(settings)
        analysis_service = MessageAnalysisService(settings)

        delivered, last_processed_message_id = asyncio.run(
            _ingest_pending_gmail_messages(
                settings=settings,
                gmail_client=gmail_client,
                pending_ids=pending_ids,
                settings_repo=settings_repo,
                mailbox_repo=mailbox_repo,
                message_repo=message_repo,
                ai_repo=ai_repo,
                analysis_service=analysis_service,
                allow_remote_ai=allow_remote_ai,
            )
        )

        return {
            "processed": len(pending_ids),
            "delivered": delivered,
            "skipped_seen": skipped_seen,
            "last_seen_gmail_tempmail_message_id": last_processed_message_id or existing_cursor or newest_seen_message_id,
            "truncated": truncated,
            "bootstrap": False,
        }
    finally:
        if owns_gmail_client:
            gmail_client.close()


def process_telegram_updates_once(
    settings: AppSettings,
    telegram_client: TelegramClient | None = None,
) -> dict[str, int | None]:
    initialize_database(settings)

    if telegram_client is None:
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required for telegram polling")
        telegram_client = TelegramClient(settings.telegram_bot_token)

    alias_repo = AliasRepository(settings)
    settings_repo = AppSettingsRepository(settings)
    last_update_id_raw = settings_repo.get(TELEGRAM_LAST_UPDATE_ID_KEY)
    offset = None if last_update_id_raw is None else int(last_update_id_raw) + 1
    updates_response = telegram_client.get_updates(offset=offset, timeout=0)
    updates = list(updates_response.get("result", []))

    handled = 0
    last_update_id: int | None = None
    for update in updates:
        if handle_update(update, settings=settings, repo=alias_repo, telegram_client=telegram_client):
            handled += 1
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            last_update_id = update_id

    if last_update_id is not None:
        settings_repo.set(TELEGRAM_LAST_UPDATE_ID_KEY, str(last_update_id))

    return {
        "processed": len(updates),
        "handled": handled,
        "last_update_id": last_update_id,
    }


def _run_iteration_step(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        print(f"[mail-telegram-app] {label} failed: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()


def run_worker_loop() -> None:
    settings = AppSettings.from_env()
    initialize_database(settings)

    has_telegram = bool(settings.telegram_bot_token)
    has_gmail_telegram_bridge = settings.has_gmail_ingest and has_telegram
    has_gmail_tempmail = settings.has_gmail_tempmail_ingest

    if not (has_telegram or has_gmail_tempmail):
        print(
            "[mail-telegram-app] worker has nothing to do: enable TELEGRAM_BOT_TOKEN or GMAIL_TEMPMAIL_ADDRESS",
            file=sys.stderr,
            flush=True,
        )

    while True:
        if has_telegram:
            _run_iteration_step("telegram polling", lambda: process_telegram_updates_once(settings))
        if has_gmail_telegram_bridge:
            _run_iteration_step("gmail->telegram bridge", lambda: process_once(settings))
        if has_gmail_tempmail:
            _run_iteration_step("gmail->tempmail ingest", lambda: process_gmail_tempmail_once(settings))
        time.sleep(settings.gmail_poll_seconds)
