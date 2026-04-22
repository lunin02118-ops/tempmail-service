from __future__ import annotations

import hashlib
import secrets


SESSION_COOKIE_NAME = "tm_session"


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(session_token: str, session_secret: str) -> str:
    digest = hashlib.sha256()
    digest.update(session_secret.encode("utf-8"))
    digest.update(b":")
    digest.update(session_token.encode("utf-8"))
    return digest.hexdigest()
