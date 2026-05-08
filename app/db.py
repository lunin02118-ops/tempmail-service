from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.engine import Engine

from app.config import AppSettings


metadata = MetaData()
_initialized_database_urls: set[str] = set()
_initialize_lock = Lock()

aliases_table = Table(
    "aliases",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("alias_local_part", String(255), nullable=False),
    Column("alias_email", String(320), nullable=False, unique=True),
    Column("telegram_chat_id", String(255), nullable=False),
    Column("telegram_user_id", String(255)),
    Column("description", Text),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("created_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
)

inbound_messages_table = Table(
    "inbound_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("gmail_message_id", String(255), nullable=False, unique=True),
    Column("internet_message_id", String(255)),
    Column("thread_id", String(255)),
    Column("alias_email", String(320)),
    Column("delivered_to", String(320)),
    Column("from_address", String(320)),
    Column("subject", Text),
    Column("received_at", Text),
    Column("body_text", Text),
    Column("body_html", Text),
    Column("raw_headers_json", Text),
    Column("parse_status", String(64)),
    Column("created_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
)

deliveries_table = Table(
    "deliveries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("inbound_message_id", Integer, ForeignKey("inbound_messages.id"), nullable=False),
    Column("telegram_chat_id", String(255), nullable=False),
    Column("telegram_message_id", String(255)),
    Column("status", String(64), nullable=False),
    Column("error_text", Text),
    Column("delivered_at", DateTime(timezone=False), server_default=func.now()),
    Column("created_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
)

app_settings_table = Table(
    "app_settings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(255), nullable=False, unique=True),
    Column("value", Text, nullable=False),
    Column("updated_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
)

mailboxes_table = Table(
    "mailboxes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("local_part", String(255), nullable=False),
    Column("domain", String(255), nullable=False),
    Column("address", String(320), nullable=False, unique=True),
    Column("visibility", String(32), nullable=False, server_default=text("'session'")),
    Column("session_token_hash", String(128), nullable=False),
    Column("description", Text),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("created_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=False)),
    Column("expires_at", DateTime(timezone=False), nullable=False),
)

messages_table = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mailbox_id", Integer, ForeignKey("mailboxes.id"), nullable=False),
    Column("source_provider", String(64), nullable=False, server_default=text("'ingest'")),
    Column("provider_message_id", String(255)),
    Column("internet_message_id", String(255)),
    Column("from_address", String(320)),
    Column("to_address", String(320)),
    Column("subject", Text),
    Column("received_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
    Column("body_text", Text),
    Column("body_html", Text),
    Column("raw_payload_json", Text),
    Column("has_attachments", Integer, nullable=False, server_default=text("0")),
    Column("is_unread", Integer, nullable=False, server_default=text("1")),
    Column("created_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
    UniqueConstraint("source_provider", "provider_message_id", name="uq_messages_provider_message"),
)

ai_extractions_table = Table(
    "ai_extractions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("message_id", Integer, ForeignKey("messages.id"), nullable=False, unique=True),
    Column("provider", String(64), nullable=False),
    Column("model", String(128)),
    Column("status", String(32), nullable=False, server_default=text("'pending'")),
    Column("summary", Text),
    Column("message_type", String(64)),
    Column("otp_code", String(32)),
    Column("action_required", String(255)),
    Column("action_links_json", Text),
    Column("sender_brand", String(255)),
    Column("confidence", String(32)),
    Column("error_text", Text),
    Column("created_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=False), nullable=False, server_default=func.now()),
)


def resolve_sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Only sqlite URLs can be resolved to filesystem paths")
    return Path(database_url[len(prefix):])


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite:///"):
        return {"future": True, "connect_args": {"check_same_thread": False}}
    return {"future": True, "pool_pre_ping": True}


@lru_cache(maxsize=16)
def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, **_engine_kwargs(database_url))


def initialize_database(settings: AppSettings) -> Path | str:
    engine = get_engine(settings.database_url)
    with _initialize_lock:
        if settings.database_url not in _initialized_database_urls:
            metadata.create_all(engine)
            _initialized_database_urls.add(settings.database_url)
    if settings.database_url.startswith("sqlite:///"):
        return resolve_sqlite_path(settings.database_url)
    return settings.database_url
