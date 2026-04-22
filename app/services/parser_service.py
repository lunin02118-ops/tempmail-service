from __future__ import annotations

import base64
import re
from email.utils import parseaddr

_HEADER_PRIORITY = (
    "Delivered-To",
    "X-Original-To",
    "To",
)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def _extract_address(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    _, address = parseaddr(raw_value)
    if address and "@" in address:
        return address.lower()
    if "@" in raw_value and " " not in raw_value.strip():
        return raw_value.strip().lower()
    match = _EMAIL_RE.search(raw_value)
    if match:
        return match.group(0).lower()
    return None


def extract_delivered_alias(headers: dict[str, str]) -> str | None:
    forwarded_for = headers.get("X-Forwarded-For")
    if forwarded_for:
        matches = [m.lower() for m in _EMAIL_RE.findall(forwarded_for)]
        for address in matches:
            if not address.endswith("@gmail.com"):
                return address

    for header_name in _HEADER_PRIORITY:
        address = _extract_address(headers.get(header_name))
        if address:
            return address
    return None


def flatten_headers(header_items: list[dict[str, str]] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in header_items or []:
        name = item.get("name")
        value = item.get("value")
        if name and value:
            result[name] = value
    return result


def decode_gmail_body(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
