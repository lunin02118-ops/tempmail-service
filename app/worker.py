from __future__ import annotations

import sys
import time
import traceback

from app.config import AppSettings
from app.db import initialize_database
from app.repositories.aliases import AliasRepository
from app.repositories.app_settings import AppSettingsRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.services.bot_service import handle_update
from app.services.gmail_client import GmailClient
from app.services.ingestion_service import ingest_gmail_message
from app.services.telegram_client import TelegramClient

LAST_SEEN_GMAIL_MESSAGE_ID_KEY = "last_seen_gmail_message_id"
TELEGRAM_LAST_UPDATE_ID_KEY = "telegram_last_update_id"
GMAIL_PAGE_SIZE = 100


def _collect_pending_message_ids(
    gmail_client: GmailClient,
    settings_repo: AppSettingsRepository,
) -> tuple[list[str], int, str | None]:
    last_seen = settings_repo.get(LAST_SEEN_GMAIL_MESSAGE_ID_KEY)
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

    gmail_client = gmail_client or GmailClient(settings)
    if telegram_client is None:
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required for worker mode")
        telegram_client = TelegramClient(settings.telegram_bot_token)

    alias_repo = AliasRepository(settings)
    message_repo = InboundMessageRepository(settings)
    settings_repo = AppSettingsRepository(settings)

    pending_ids, skipped_seen, newest_seen_message_id = _collect_pending_message_ids(gmail_client, settings_repo)

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


def run_worker_loop() -> None:
    settings = AppSettings.from_env()
    initialize_database(settings)

    while True:
        try:
            process_telegram_updates_once(settings)
            process_once(settings)
        except Exception as exc:
            print(f"[mail-telegram-app] worker iteration failed: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc()
        time.sleep(settings.gmail_poll_seconds)
