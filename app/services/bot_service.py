from __future__ import annotations

from app.config import AppSettings
from app.repositories.aliases import AliasRepository
from app.schemas.alias import AliasResponse
from app.services.alias_service import generate_alias_local_part, normalize_alias_email

GENERATE_ALIAS_TEXT = "Сгенерировать почту"
MAIN_KEYBOARD = {
    "keyboard": [[{"text": GENERATE_ALIAS_TEXT}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
    "is_persistent": False,
    "input_field_placeholder": "Нажмите кнопку или введите /start",
}


def create_alias_for_chat(
    settings: AppSettings,
    repo: AliasRepository,
    telegram_chat_id: str,
    telegram_user_id: str | None,
    description: str | None = None,
    local_part_length: int = 8,
) -> AliasResponse:
    if not settings.default_from_alias_domain:
        raise ValueError("DEFAULT_FROM_ALIAS_DOMAIN is not configured")

    for _ in range(10):
        local_part = generate_alias_local_part(local_part_length)
        alias_email = normalize_alias_email(local_part, settings.default_from_alias_domain)
        if repo.get_by_alias_email(alias_email) is None:
            alias_id = repo.create_alias(
                alias_local_part=local_part,
                alias_email=alias_email,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                description=description,
            )
            return AliasResponse(
                id=alias_id,
                alias_local_part=local_part,
                alias_email=alias_email,
                telegram_chat_id=telegram_chat_id,
                telegram_user_id=telegram_user_id,
                description=description,
                is_active=True,
            )

    raise RuntimeError("failed to generate unique alias")


def build_welcome_message() -> str:
    return "Нажмите «Сгенерировать почту», и я создам для вас адрес для входящих писем."


def build_alias_created_message(alias_email: str) -> str:
    return (
        f"Ваша почта: {alias_email}\n\n"
        "Теперь я сам проверяю входящие и сразу покажу новые письма в этом чате."
    )


def build_unknown_command_message() -> str:
    return "Используйте кнопку «Сгенерировать почту»."


def extract_message_context(update: dict) -> tuple[str | None, str | None, str | None]:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    text = message.get("text")
    chat_id = chat.get("id")
    user_id = user.get("id")
    return (
        str(chat_id) if chat_id is not None else None,
        str(user_id) if user_id is not None else None,
        text,
    )


def handle_update(update: dict, settings: AppSettings, repo: AliasRepository, telegram_client) -> bool:
    chat_id, user_id, text = extract_message_context(update)
    if not chat_id or not text:
        return False

    normalized_text = text.strip()
    if normalized_text == "/start":
        telegram_client.send_message(chat_id, build_welcome_message(), reply_markup=MAIN_KEYBOARD)
        return True

    if normalized_text == GENERATE_ALIAS_TEXT:
        alias = create_alias_for_chat(
            settings=settings,
            repo=repo,
            telegram_chat_id=chat_id,
            telegram_user_id=user_id,
        )
        telegram_client.send_message(chat_id, build_alias_created_message(alias.alias_email), reply_markup=MAIN_KEYBOARD)
        return True

    telegram_client.send_message(chat_id, build_unknown_command_message(), reply_markup=MAIN_KEYBOARD)
    return True
