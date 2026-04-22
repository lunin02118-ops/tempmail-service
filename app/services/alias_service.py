from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def generate_alias_local_part(length: int = 8) -> str:
    if length <= 0:
        raise ValueError("length must be positive")
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def normalize_alias_email(local_part: str, domain: str) -> str:
    clean_local = local_part.strip().lower()
    clean_domain = domain.strip().lower()
    if not clean_local or not clean_domain:
        raise ValueError("local_part and domain are required")
    return f"{clean_local}@{clean_domain}"
