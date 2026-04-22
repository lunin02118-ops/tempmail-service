from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_local_env_file() -> None:
    if os.getenv("APP_ENV") == "test" or "PYTEST_CURRENT_TEST" in os.environ:
        return

    loaded_values: dict[str, str] = {}
    for env_name in (".env", ".env.local"):
        env_path = PROJECT_ROOT / env_name
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            loaded_values[key.strip()] = value.strip()

    for key, value in loaded_values.items():
        os.environ.setdefault(key, value)


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _resolve_database_url(database_url: str) -> str:
    normalized = _normalize_database_url(database_url)
    prefix = "sqlite:///"
    if not normalized.startswith(prefix):
        return normalized

    raw_path = normalized[len(prefix):]
    resolved_path = _resolve_project_path(raw_path)
    return f"{prefix}{resolved_path}"


def _resolve_optional_path(env_name: str) -> Path | None:
    raw = os.getenv(env_name)
    if not raw:
        return None
    return _resolve_project_path(raw)


def _split_csv_env(env_name: str) -> tuple[str, ...]:
    raw = os.getenv(env_name, "")
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return tuple(values)


def _resolve_groq_api_keys() -> tuple[str, ...]:
    csv_values = _split_csv_env("GROQ_API_KEYS")
    if csv_values:
        return csv_values

    numbered_values: list[str] = []
    index = 1
    while True:
        value = os.getenv(f"GROQ_API_KEY_{index}")
        if not value:
            break
        cleaned = value.strip()
        if cleaned:
            numbered_values.append(cleaned)
        index += 1

    return tuple(numbered_values)


@dataclass(slots=True)
class AppSettings:
    project_root: Path
    app_env: str
    database_url: str
    database_url_direct: str | None
    public_mail_domain: str
    app_base_url: str | None
    app_host: str
    app_port: int
    log_level: str
    session_secret: str
    ingest_webhook_secret: str | None
    turnstile_site_key: str | None
    turnstile_secret_key: str | None
    cloudflare_api_token: str | None
    cloudflare_account_id: str | None
    cloudflare_zone_id: str | None
    groq_api_keys: tuple[str, ...]
    groq_model: str
    mailbox_default_ttl_minutes: int
    alias_api_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    gmail_client_secret_path: Path | None = None
    gmail_token_path: Path | None = None
    gmail_poll_seconds: int = 60
    default_from_alias_domain: str = ""
    neon_api_key: str | None = None
    render_api_key: str | None = None
    r2_bucket_name: str | None = None
    r2_public_base_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None

    @property
    def active_mail_domain(self) -> str:
        return self.public_mail_domain or self.default_from_alias_domain

    @property
    def has_gmail_ingest(self) -> bool:
        return self.gmail_client_secret_path is not None and self.gmail_token_path is not None

    @classmethod
    def from_env(cls) -> "AppSettings":
        _load_local_env_file()

        database_url = _resolve_database_url(os.getenv("DATABASE_URL", "sqlite:///./data/app.db"))
        database_url_direct_raw = os.getenv("DATABASE_URL_DIRECT")
        database_url_direct = None
        if database_url_direct_raw:
            database_url_direct = _resolve_database_url(database_url_direct_raw)

        public_mail_domain = os.getenv("PUBLIC_MAIL_DOMAIN", os.getenv("DEFAULT_FROM_ALIAS_DOMAIN", ""))
        session_secret = os.getenv("SESSION_SECRET")
        if not session_secret:
            session_secret = "test-session-secret" if os.getenv("APP_ENV") == "test" else "dev-session-secret"

        return cls(
            project_root=PROJECT_ROOT,
            app_env=os.getenv("APP_ENV", "prod"),
            database_url=database_url,
            database_url_direct=database_url_direct,
            public_mail_domain=public_mail_domain.strip().lower(),
            app_base_url=os.getenv("APP_BASE_URL"),
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "8787")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            session_secret=session_secret,
            ingest_webhook_secret=os.getenv("INGEST_WEBHOOK_SECRET"),
            turnstile_site_key=os.getenv("TURNSTILE_SITE_KEY"),
            turnstile_secret_key=os.getenv("TURNSTILE_SECRET_KEY"),
            cloudflare_api_token=os.getenv("CLOUDFLARE_API_TOKEN"),
            cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID"),
            cloudflare_zone_id=os.getenv("CLOUDFLARE_ZONE_ID"),
            groq_api_keys=_resolve_groq_api_keys(),
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            mailbox_default_ttl_minutes=int(os.getenv("MAILBOX_DEFAULT_TTL_MINUTES", "60")),
            alias_api_token=os.getenv("ALIAS_API_TOKEN"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET"),
            gmail_client_secret_path=_resolve_optional_path("GMAIL_CLIENT_SECRET_PATH"),
            gmail_token_path=_resolve_optional_path("GMAIL_TOKEN_PATH"),
            gmail_poll_seconds=int(os.getenv("GMAIL_POLL_SECONDS", "60")),
            default_from_alias_domain=os.getenv("DEFAULT_FROM_ALIAS_DOMAIN", "").strip().lower(),
            neon_api_key=os.getenv("NEON_API_KEY"),
            render_api_key=os.getenv("RENDER_API_KEY"),
            r2_bucket_name=os.getenv("R2_BUCKET_NAME"),
            r2_public_base_url=os.getenv("R2_PUBLIC_BASE_URL"),
            r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        )
