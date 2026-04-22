from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import AppSettings
from app.repositories.aliases import AliasRepository
from app.services.bot_service import handle_update
from app.services.telegram_client import TelegramClient

router = APIRouter(prefix="/telegram", tags=["telegram"])


class _TelegramClientDependency:
    value = None


def set_telegram_client_dependency(client) -> None:
    _TelegramClientDependency.value = client


def get_settings() -> AppSettings:
    return AppSettings.from_env()


def get_alias_repository(settings: AppSettings = Depends(get_settings)) -> AliasRepository:
    return AliasRepository(settings)


def verify_telegram_webhook_secret(
    settings: AppSettings = Depends(get_settings),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> None:
    expected_secret = settings.telegram_webhook_secret
    if not expected_secret:
        return

    if x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid telegram webhook secret")


def get_telegram_client(settings: AppSettings = Depends(get_settings)):
    if _TelegramClientDependency.value is not None:
        return _TelegramClientDependency.value
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required for telegram webhook")
    return TelegramClient(settings.telegram_bot_token)


@router.post("/webhook")
def telegram_webhook(
    update: dict,
    settings: AppSettings = Depends(get_settings),
    repo: AliasRepository = Depends(get_alias_repository),
    _: None = Depends(verify_telegram_webhook_secret),
    telegram_client=Depends(get_telegram_client),
) -> dict[str, bool]:
    handle_update(update, settings=settings, repo=repo, telegram_client=telegram_client)
    return {"ok": True}
