from __future__ import annotations

import re
import secrets
import string

from app.config import AppSettings
from app.repositories.mailboxes import MailboxRepository


_MAILBOX_ALPHABET = string.ascii_lowercase + string.digits
_MAILBOX_LOCAL_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{2,31})$")


def generate_mailbox_local_part(length: int = 10) -> str:
    if length <= 0:
        raise ValueError("length must be positive")
    return "".join(secrets.choice(_MAILBOX_ALPHABET) for _ in range(length))


def normalize_mailbox_address(local_part: str, domain: str) -> str:
    clean_local_part = local_part.strip().lower()
    clean_domain = domain.strip().lower()
    if not clean_local_part or not clean_domain:
        raise ValueError("local_part and domain are required")
    return f"{clean_local_part}@{clean_domain}"


def validate_requested_local_part(local_part: str) -> str:
    normalized = local_part.strip().lower()
    if not _MAILBOX_LOCAL_PART_RE.fullmatch(normalized):
        raise ValueError(
            "requested_local_part must start with a letter or digit and contain 3-32 lowercase characters"
        )
    return normalized


class MailboxService:
    def __init__(self, settings: AppSettings, repo: MailboxRepository) -> None:
        self._settings = settings
        self._repo = repo

    def _resolve_mailbox_domain(self, requested_domain: str | None) -> str:
        available_domains = self._settings.available_mail_domains
        if not available_domains:
            raise RuntimeError("PUBLIC_MAIL_DOMAIN or PUBLIC_MAIL_DOMAINS is not configured")

        if requested_domain:
            normalized = requested_domain.strip().lower()
            if normalized not in available_domains:
                raise ValueError("requested_domain is not available")
            return normalized

        return available_domains[0]

    def create_mailbox(
        self,
        *,
        session_token_hash: str,
        description: str | None = None,
        expires_in_minutes: int | None = None,
        requested_local_part: str | None = None,
        requested_domain: str | None = None,
        local_part_length: int = 10,
    ) -> dict[str, object]:
        domain = self._resolve_mailbox_domain(requested_domain)

        if requested_local_part:
            local_part = validate_requested_local_part(requested_local_part)
            address = normalize_mailbox_address(local_part, domain)
            if self._repo.get_by_address(address) is not None:
                raise FileExistsError("requested mailbox address already exists")
            return self._repo.create_mailbox(
                local_part=local_part,
                domain=domain,
                address=address,
                session_token_hash=session_token_hash,
                description=description,
                expires_in_minutes=expires_in_minutes,
            )

        for _ in range(25):
            local_part = generate_mailbox_local_part(local_part_length)
            address = normalize_mailbox_address(local_part, domain)
            if self._repo.get_by_address(address) is None:
                return self._repo.create_mailbox(
                    local_part=local_part,
                    domain=domain,
                    address=address,
                    session_token_hash=session_token_hash,
                    description=description,
                    expires_in_minutes=expires_in_minutes,
                )

        raise RuntimeError("failed to generate a unique mailbox")
